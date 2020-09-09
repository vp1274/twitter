import os
import logging
import argparse
import pandas as pd
import numpy as np
import pytz
import pyarrow
from pathlib import Path
from transformers import BertTokenizer

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
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    print("test", flush=True)
    # Define args from command line
    args = get_args_from_command_line()
    # Import inference data
    random_data_dir = Path('/scratch/spf248/twitter/data/classification/US/random')
    full_random_df = pd.concat(pd.read_parquet(parquet_file, columns=['tweet_id', 'text']) for parquet_file in
                               random_data_dir.glob('*.parquet'))
    full_random_df = full_random_df.set_index(['tweet_id'])
    print("Loaded all random data", flush=True)
    # Load tokenizer and tokenize text
    tokenizer = BertTokenizer.from_pretrained('DeepPavlov/bert-base-cased-conversational')
    full_random_df['tokenized_text'] = full_random_df['text'].apply(tokenizer.tokenize)
    print("Tokenized text", flush=True)
    full_random_df = full_random_df.explode('tokenized_text')
    full_random_count_df = full_random_df['tokenized_text'].value_counts().rename_axis('word').reset_index(name='count')
    full_random_count_df.to_parquet(
        '/scratch/mt4493/twitter_labor/twitter-labor-data/data/wordcount_random/wordcount_random.parquet', index=False)
    print(
        "Saved word count to /scratch/mt4493/twitter_labor/twitter-labor-data/data/wordcount_random/wordcount_random.parquet'",
        flush=True)