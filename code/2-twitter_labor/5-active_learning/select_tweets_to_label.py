import os
import logging
import argparse
import pandas as pd
import numpy as np
import pytz
import pyarrow
from pathlib import Path
from transformers import BertTokenizer, BertModel, BertConfig, BertForTokenClassification, pipeline, \
    AutoModelForTokenClassification, AutoTokenizer
import torch

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(name)s -   %(message)s',
                    datefmt='%m/%d/%Y %H:%M:%S',
                    level=logging.INFO)
logger = logging.getLogger(__name__)


def get_args_from_command_line():
    """Parse the command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--inference_output_folder", type=str,
                        help="Path to the inference data. Must be in csv format.",
                        default="")
    parser.add_argument("--N_exploit", type=int, help="Number of tweets to label for exploitation.", default="")
    parser.add_argument("--N_explore_kw", type=int, help="Number of tweets to label for keyword explore.",
                        default="")
    parser.add_argument("--K_tw_exploit", type=int, help="Number of top tweets to study for exploitation.", default="")
    parser.add_argument("--K_tw_explore_kw", type=int, help="Number of top tweets to study for keyword explore.",
                        default="")
    parser.add_argument("--K_tw_explore_sent", type=int, help="Number of top tweets to study for sentence explore.",
                        default="")
    parser.add_argument("--K_kw_explore", type=int,
                        help="Number of keywords to select for keyword explore.", default="")

    args = parser.parse_args()
    return args


def get_token_in_sequence_with_most_attention(model, tokenizer, input_sequence):
    """Run an input sequence through the BERT model, collect and average attention scores per token and return token with most average attention."""
    tokenized_input_sequence = tokenizer.tokenize(input_sequence)
    input_ids = torch.tensor(tokenizer.encode(input_sequence, add_special_tokens=False)).unsqueeze(0)
    outputs = model(input_ids)
    last_hidden_states, pooler_outputs, hidden_states, attentions = outputs
    attention_tensor = torch.squeeze(torch.stack(attentions))
    attention_tensor_averaged = torch.mean(attention_tensor, (0, 1))
    attention_average_scores_per_token = torch.sum(attention_tensor_averaged, dim=0)
    attention_scores_dict = dict()
    for token_position in range(len(tokenized_input_sequence)):
        attention_scores_dict[token_position] = attention_average_scores_per_token[token_position].item()
    print(attention_scores_dict)
    return {'token_index': max(attention_scores_dict, key=attention_scores_dict.get),
            'token_str': tokenized_input_sequence[max(attention_scores_dict, key=attention_scores_dict.get)]}


def word_count(df, column):
    df = df[:label2rank[column]]
    df_wordcount = df.explode('tokenized_text')
    df_wordcount = df_wordcount['tokenized_text'].value_counts().rename_axis('word').reset_index(
        name='count_top_tweets')


def extract_keywords_from_mlm_results(mlm_results_list, K_kw_explore):
    selected_keywords_list = list()
    for rank_mlm_keyword in range(K_kw_explore):
        selected_keywords_list.append(mlm_results_list[rank_mlm_keyword]['token_str'])
    return selected_keywords_list


if __name__ == "__main__":
    # Define args from command line
    args = get_args_from_command_line()
    mlm_pipeline = pipeline('fill-mask', model='bert-base-uncased', tokenizer='bert-base-uncased',
                            config='bert-base-uncased', topk=10)
    labels = ['is_hired_1mo', 'is_unemployed', 'job_offer', 'job_search', 'lost_job_1mo']
    base_rates = [
        1.7342911457049017e-05,
        0.0003534645020523677,
        0.005604641971672389,
        0.00015839552996469054,
        1.455338466552472e-05]
    N_random = 92114009
    base_ranks = [int(x * N_random) for x in base_rates]
    label2rank = dict(zip(labels, base_ranks))
    for column in labels:
        # Load model, config and tokenizer
        config = BertConfig.from_pretrained(PATH_MODEL_FOLDER, output_hidden_states=True, output_attentions=True)
        tokenizer = BertTokenizer.from_pretrained(PATH_MODEL_FOLDER)
        model = BertModel.from_pretrained(PATH_MODEL_FOLDER, config=config)
        # Load data
        input_parquet_path = os.path.join(args.inference_output_folder, column, "{}_all.parquet".format(column))
        all_data_df = pd.read_parquet(input_parquet_path)
        all_data_df = all_data_df.sort_values(by=["score"], ascending=False).reset_index()
        all_data_df['tokenized_text'] = all_data_df['text'].apply(tokenizer.tokenize)
        # exploit (final data in exploit_data_df)
        exploit_data_df = all_data_df[:args.N_exploit]
        # explore (w/ keyword lift; final data in explore_kw_data_df)
        nb_tweets_per_keyword = int(args.N_explore_kw / args.K_kw_explore)
        explore_kw_data_df = all_data_df[:args.K_tw_explore_kw]
        explore_kw_wordcount_df = explore_kw_data_df.explode('tokenized_text')
        explore_kw_wordcount_df = explore_kw_wordcount['tokenized_text'].value_counts().rename_axis(
            'word').reset_index(name='count_top_tweets')
        full_random_wordcount_df = pd.read_parquet(
            '/scratch/mt4493/twitter_labor/twitter-labor-data/data/wordcount_random/wordcount_random.parquet')
        explore_kw_wordcount_df = explore_kw_wordcount_df.join(full_random_wordcount_df, on=['word'])
        explore_kw_wordcount_df['lift'] = (explore_kw_wordcount_df['count_top_tweets'] /
                                               explore_kw_wordcount_df['count']) * N_random / label2rank[column]
        explore_kw_wordcount_df = explore_kw_wordcount_df.sort_values(by=["lift"],
                                                                              ascending=False).reset_index()
        selected_keywords_list = explore_kw_wordcount_df['word'][:args.K_kw_explore].tolist()
        for selected_keyword in selected_keywords_list:
            tweets_containing_keyword_df = all_data_df[all_data_df['text'].str.contains(keyword)]
            if tweets_containing_keyword_df.shape[0] < nb_tweets_per_keyword:
                print("Only {} tweets containing keyword {} (< {}). Sending all of them to labelling.".format(
                    str(tweets_containing_keyword_df.shape[0]), keyword, str(nb_tweets_per_keyword)))
                explore_kw_data_df = tweets_containing_keyword_df
            else:
                explore_kw_data_df = tweets_containing_keyword_df.sample(n=nb_tweets_per_keyword)

        # explore (attention version)
        # explore_kw_data_df = all_data_df[:args.K_tw_explore_kw]
        # nb_tweets_per_keyword = args.N_explore_kw // (args.K_tw_explore_kw * args.K_kw_explore)
        # for tweet_rank in range(explore_kw_data_df.shape[0]):
        #    tweet_str = explore_kw_data_df['text'][tweet_rank]
        #    tokenized_tweet = tokenizer.tokenize(tweet)
        #    # Determine the token with the highest average attention and replace it with a [MASK] token
        #    attention_token_index = \
        #    get_token_in_sequence_with_most_attention(model=model, tokenizer=tokenizer, input_sequence=tokenized_tweet)[
        #        'token_index']
        #    tokenized_tweet[attention_token_index] = '[MASK]'
        #    # Do MLM and select the top K_kw_explore keywords
        #    mlm_results_list = mlm_pipeline(' '.join(tokenized_tweet))
        #    selected_keywords_list = extract_keywords_from_mlm_results(mlm_results_list, args.K_kw_explore)
        #    # For each keyword W, draw a random sample of nb_tweets_per_keyword tweets containing W
        #    for selected_keyword in selected_keywords_list:
        ## Don't forget to lower