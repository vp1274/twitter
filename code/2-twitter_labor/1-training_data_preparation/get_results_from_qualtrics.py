import requests
import zipfile
import json
import io, os
import sys
import re
import socket
import pandas as pd
import reverse_geocoder as rg
import numpy as np
from glob import glob
import argparse


def get_args_from_command_line():
    """Parse the command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--country_code", type=str,
                        default="US")
    parser.add_argument("--surveyId", type=str)
    parser.add_argument("--block_size", type=int, help="number of tweets per worker",
                        default=50)
    parser.add_argument("--version_number", type=str)
    args = parser.parse_args()
    return args


def exportSurvey(apiToken, surveyId, dataCenter, fileFormat, path_to_data):
    surveyId = surveyId
    fileFormat = fileFormat
    dataCenter = dataCenter

    # Setting static parameters
    requestCheckProgress = 0.0
    progressStatus = "inProgress"
    baseUrl = "https://{0}.qualtrics.com/API/v3/responseexports/".format(dataCenter)
    headers = {
        "content-type": "application/json",
        "x-api-token": apiToken,
    }

    # Step 1: Creating Data Export
    downloadRequestUrl = baseUrl
    downloadRequestPayload = '{"format":"' + fileFormat + '","surveyId":"' + surveyId + '"}'
    downloadRequestResponse = requests.request("POST", downloadRequestUrl, data=downloadRequestPayload, headers=headers)
    progressId = downloadRequestResponse.json()["result"]['id']
    print(downloadRequestResponse.text)

    # Step 2: Checking on Data Export Progress and waiting until export is ready
    while progressStatus != "complete" and progressStatus != "failed":
        print("progressStatus=", progressStatus)
        requestCheckUrl = baseUrl + progressId
        requestCheckResponse = requests.request("GET", requestCheckUrl, headers=headers)
        requestCheckProgress = requestCheckResponse.json()["result"]["percentComplete"]
        print("Download is " + str(requestCheckProgress) + " complete")
        progressStatus = requestCheckResponse.json()["result"]["status"]

    # step 2.1: Check for error
    if progressStatus is "failed":
        raise Exception("export failed")

    # # Step 3: Downloading file
    requestDownloadUrl = baseUrl + progressId + '/file'
    requestDownload = requests.request("GET", requestDownloadUrl, headers=headers, stream=True)

    # Step 4: Unzipping the file
    zipfile.ZipFile(io.BytesIO(requestDownload.content)).extractall(
        os.path.join(path_to_data, surveyId))
    print('Complete')


if __name__ == "__main__":
    args = get_args_from_command_line()
    path_to_data = f'/scratch/mt4493/twitter_labor/twitter-labor-data/data/qualtrics/{args.country_code}/labeling'
    with open('/scratch/mt4493/twitter_labor/twitter-labor-data/data/qualtrics/keys/apiToken.txt', 'r') as f:
        apiToken = f.readline()
    # Export Survey
    if not os.path.exists(
            os.path.join(path_to_data, args.surveyId)):
        if not re.compile('^SV_.*').match(args.surveyId):
            print("survey Id must match ^SV_.*")
        else:
            exportSurvey(apiToken=apiToken, surveyId=args.surveyId, dataCenter='nyu.ca1', fileFormat='csv',
                         path_to_data=path_to_data)
    file_path = \
    [file for file in glob(os.path.join(path_to_data, args.surveyId, '*.csv')) if 'labor-market-tweets' in file][0]
    # Analyse Results
    df = pd.read_csv(file_path, low_memory=False)
    # First two rows contain metadata
    df.drop([0, 1], inplace=True)

    df = df.loc[(df['QIDWorker'].dropna().drop_duplicates().index)].set_index('QIDWorker').copy()

    places = rg.search(
        [tuple(x) for x in df[['LocationLatitude', 'LocationLongitude']].astype(float).dropna().values.tolist()])

    print('# of workers who refused the consent form:', (df.QIDConsent.astype(int) == 0).sum())
    print('# of workers who did not complete the survey:', (df.Finished.astype(int) == 0).sum())

    to_drop = [
        'ResponseID',
        'ResponseSet',
        'IPAddress',
        'StartDate',
        'EndDate',
        'RecipientLastName',
        'RecipientFirstName',
        'RecipientEmail',
        'ExternalDataReference',
        'Finished',
        'Status',
        'Random ID',
        'QIDConsent',
        'QIDDescription',
        'QIDCompletion',
        'LocationLatitude',
        'LocationLongitude',
        'LocationAccuracy']

    df.drop(to_drop, 1, inplace=True, errors='ignore')
    df.drop([x for x in df.columns if 'BR-FL_' in x], 1, inplace=True, errors='ignore')
    print('# Workers:', df.shape[0])