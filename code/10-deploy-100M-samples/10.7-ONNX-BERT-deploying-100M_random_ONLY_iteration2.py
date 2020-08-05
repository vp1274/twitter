#!/usr/bin/env python
# coding: utf-8

print('running 10.7-ONNX-BERT-deploying-100M_random_ONLY_iteration2.py')

import sys
import os
import torch
import onnxruntime as ort
import argparse
import pandas as pd
import numpy as np
import os
import time
import torch.nn.functional as F
import onnx
import getpass

sys.path.append('/scratch/da2734/twitter/jobs/inference_200M/utils_for_inference')
from onnxruntime_tools import optimizer
from transformers import BertConfig, BertTokenizer, BertTokenizerFast, BertForSequenceClassification

print('libs loaded')

import argparse

parser = argparse.ArgumentParser()

parser.add_argument("--model_path", help="path to pytorch models (with onnx model in model_path/onnx/")
parser.add_argument("--output_path", help="path where inference csv is saved")

args = parser.parse_args()

print(args)


####################################################################################################################################
# HELPER FUNCTIONS
####################################################################################################################################

# inference
def get_tokens(tokens_dict, i):
    i_tokens_dict = dict()
    for key in ['input_ids', 'token_type_ids', 'attention_mask']:
        i_tokens_dict[key] = tokens_dict[key][i]
    tokens = {name: np.atleast_2d(value) for name, value in i_tokens_dict.items()}
    return tokens


def inference(onnx_model, model_dir, examples, fast_tokenizer, num_threads):
    quantized_str = ''
    if 'quantized' in onnx_model:
        quantized_str = 'quantized'
    onnx_inference = []
    #     pytorch_inference = []
    # onnx session
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.intra_op_num_threads = 1
    print(onnx_model)
    ort_session = ort.InferenceSession(onnx_model, options)

    # pytorch pretrained model and tokenizer
    tokenizer = BertTokenizerFast.from_pretrained(model_dir)
    tokenizer_str = "BertTokenizerFast"

    print("**************** {} ONNX inference with batch tokenization and with {} tokenizer****************".format(
        quantized_str, tokenizer_str))
    start_onnx_inference_batch = time.time()
    start_batch_tokenization = time.time()
    tokens_dict = tokenizer.batch_encode_plus(examples, max_length=128)
    total_batch_tokenization_time = time.time() - start_batch_tokenization
    total_inference_time = 0
    total_build_label_time = 0
    for i in range(len(examples)):
        """
        Onnx inference with batch tokenization
        """

        if i % 100 == 0:
            print('[inference... ]', i, 'out of ', len(examples))

        tokens = get_tokens(tokens_dict, i)
        # inference
        start_inference = time.time()
        ort_outs = ort_session.run(None, tokens)
        total_inference_time = total_inference_time + (time.time() - start_inference)
        # build label
        start_build_label = time.time()
        torch_onnx_output = torch.tensor(ort_outs[0], dtype=torch.float32)
        onnx_logits = F.softmax(torch_onnx_output, dim=1)
        logits_label = torch.argmax(onnx_logits, dim=1)
        label = logits_label.detach().cpu().numpy()
        #         onnx_inference.append(label[0])
        onnx_inference.append(onnx_logits.detach().cpu().numpy()[0].tolist())
        total_build_label_time = total_build_label_time + (time.time() - start_build_label)
    #         print(i, label[0], onnx_logits.detach().cpu().numpy()[0].tolist(), type(onnx_logits.detach().cpu().numpy()[0]) )

    end_onnx_inference_batch = time.time()
    print("Total batch tokenization time (in seconds): ", total_batch_tokenization_time)
    print("Total inference time (in seconds): ", total_inference_time)
    print("Total build label time (in seconds): ", total_build_label_time)
    print("Duration ONNX inference (in seconds) with {} and batch tokenization: ".format(tokenizer_str),
          end_onnx_inference_batch - start_onnx_inference_batch,
          (end_onnx_inference_batch - start_onnx_inference_batch) / len(examples))

    return onnx_inference


def get_env_var(varname, default):
    if os.environ.get(varname) != None:
        var = int(os.environ.get(varname))
        print(varname, ':', var)
    else:
        var = default
        print(varname, ':', var, '(Default)')
    return var


# Choose Number of Nodes To Distribute Credentials: e.g. jobarray=0-4, cpu_per_task=20, credentials = 90 (<100)
SLURM_ARRAY_TASK_ID = get_env_var('SLURM_ARRAY_TASK_ID', 0)
SLURM_ARRAY_TASK_COUNT = get_env_var('SLURM_ARRAY_TASK_COUNT', 1)

# SLURM_JOB_ID = 123123123
# SLURM_ARRAY_TASK_ID = 10
# SLURM_ARRAY_TASK_COUNT = 500


print('SLURM_ARRAY_TASK_ID', SLURM_ARRAY_TASK_ID)
print('SLURM_ARRAY_TASK_COUNT', SLURM_ARRAY_TASK_COUNT)
# ####################################################################################################################################
# # loading data
# ####################################################################################################################################

import time
import pyarrow.parquet as pq
from glob import glob
import os
import numpy as np

path_to_data = '/scratch/spf248/twitter/data/classification/US/'

print('Load random Tweets:')

start_time = time.time()

paths_to_random = list(np.array_split(
    glob(os.path.join(path_to_data, 'random', '*.parquet')),
    #                         glob(os.path.join(path_to_data,'random_first_half','*.parquet')),
    #                         glob(os.path.join(path_to_data,'random_10perct_sample','*.parquet')),
    #                         glob(os.path.join(path_to_data,'random_1perct_sample','*.parquet')),
    SLURM_ARRAY_TASK_COUNT)[SLURM_ARRAY_TASK_ID])
print('#files:', len(paths_to_random))

tweets_random = pd.DataFrame()
for file in paths_to_random:
    print(file)
    tweets_random = pd.concat([tweets_random, pd.read_parquet(file)[['tweet_id', 'text']]])
    print(tweets_random.shape)

#     break #DEBUG

print('load random sample:', str(time.time() - start_time), 'seconds')
print(tweets_random.shape)

print('dropping duplicates:')
# random contains 7.3G of data!!
start_time = time.time()
tweets_random = tweets_random.drop_duplicates('text')
print('drop duplicates:', str(time.time() - start_time), 'seconds')
print(tweets_random.shape)

# tweets_random = tweets_random[:20] #DEBUG

start_time = time.time()
print('converting to list')
examples = tweets_random.text.values.tolist()

print('convert to list:', str(time.time() - start_time), 'seconds')
model_folder_name = op.basename(op.abspath(op.join(args.model_path, op.pardir, op.pardir, op.pardir)))

for column in ["is_unemployed", "lost_job_1mo", "job_search", "is_hired_1mo", "job_offer"]:

    print('\n\n!!!!!', column)
    loop_start = time.time()

    model_path = args.model_path.format(column)
    model_folder_name = op.basename(op.abspath(op.join(model_path, op.pardir, op.pardir, op.pardir)))

    print(model_path)
    onnx_path = model_path + '/onnx/'
    print(onnx_path)

    ####################################################################################################################################
    # TOKENIZATION and INFERENCE 
    ####################################################################################################################################
    print('Predictions of random Tweets:')
    start_time = time.time()
    onnx_labels = inference(onnx_path + 'bert_optimized.onnx',
                            model_path,
                            examples,
                            fast_tokenizer=True,
                            num_threads=5)

    print('time taken:', str(time.time() - start_time), 'seconds')
    print('per tweet:', (time.time() - start_time) / tweets_random.shape[0], 'seconds')

    ####################################################################################################################################
    # SAVING
    ####################################################################################################################################        
    print('Save Predictions of random Tweets:')
    start_time = time.time()

    if not os.path.exists(os.path.join(args.output_path, column)):
        print('>>>> directory doesnt exists, creating it')
        os.makedirs(os.path.join(args.output_path, column))

    predictions_random_df = pd.DataFrame(data=onnx_labels, columns=['first', 'second'])
    predictions_random_df = predictions_random_df.set_index(tweets_random.tweet_id)

    print(predictions_random_df.head())
    predictions_random_df.to_csv(
        os.path.join(args.output_path, column,
                     str(getpass.getuser()) + '_random' + '-' + str(SLURM_ARRAY_TASK_ID) + '.csv'))

    print('saved to:\n', os.path.join(args.output_path, column,
                                      str(getpass.getuser()) + '_random' + '-' + str(SLURM_ARRAY_TASK_ID) + '.csv'),
          'saved')

    print('save time taken:', str(time.time() - start_time), 'seconds')

    print('full loop:', str(time.time() - loop_start), 'seconds', (time.time() - loop_start) / len(examples))

#     break
