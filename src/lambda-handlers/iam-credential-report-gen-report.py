####################################################################
##  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
##  SPDX-License-Identifier: MIT-0
####################################################################
##  iam-cred-report-gen-report
##
##      input fields
##          accountId   : required, the AWS account id to process
##          LoopAgain   : default "yes"
##                          Controls the looping in the Step function
##          LoopCount   : default 0
##                          Keeps track of the number of times we have looped
##          funcState   : default "not complete"
##                          A state of "complete" indicates success
##                          A state of "error" indicates an error
##
##      output fields
##          All the input fields
##          reportFileName :    The name of the s3 file created
##                              under the date folder in the bucket
##

import json
import os
import boto3
import time
import logging
import sys
import botocore
import tempfile

from datetime import date


logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)  # use level DEBUG for more details

## Define current date
today = str(date.today())

###############################################################################
##  Get ENV Vars

## Read environment Variables from Lambda Function
BUCKET_ARN = os.getenv('BUCKET_ARN')
if not BUCKET_ARN:
    raise Exception ("Missing BUCKET_ARN value")
logger.debug ("BUCKET_ARN: %s" % (BUCKET_ARN))

ASSUME_ROLE_NAME = os.getenv('ASSUME_ROLE_NAME')
if not ASSUME_ROLE_NAME:
    raise Exception ("Missing ASSUME_ROLE_NAME value")
logger.debug ("ASSUME_ROLE_NAME: %s" % (ASSUME_ROLE_NAME))

MAX_LOOP = os.getenv ('MAX_LOOP')
if not MAX_LOOP:
    MAX_LOOP = '15'
if not MAX_LOOP.isnumeric():
    raise Exception ("MAX_LOOP is not numeric: %s" % (MAX_LOOP))


###############################################################################
## Setup bucket for storing reports and get stsClient
s3 = boto3.resource('s3')
bucketName = BUCKET_ARN.split(":", -1)[-1]
bucketConnection = s3.Bucket(bucketName)
    
stsClient = boto3.client('sts')

###############################################################################
## Function to handle the temp file and S3 bucket upload
def write_to_temp_and_upload(filename,content):
    tmpdir = tempfile.mkdtemp()

    full_path = os.path.join(tmpdir, filename)
    #print(full_path)
    try:
        with open(full_path, "w") as tmp:
            tmp.write(content)
    except IOError as e:
        print('IOError: Unable to write IAM Credential Report to Temp File.')
    finally:
        s3.Object(bucketName, today+"/"+filename).put(Body=open(full_path, 'rb'))
        ## to avoid the lambda tmp space from filling, remove the file we created
        os.remove(full_path)
        ## this is used to remove the empty directory. 
        ## OSError will be raised if the specified path is not an empty directory.
        os.rmdir(tmpdir)
        



###############################################################################
## main

def lambda_handler(event, context):

    ## Log what we were passed
    logger.debug ("Input event: %s" % (json.dumps (event)))
    logger.debug ("MAX_LOOP: %s" % (MAX_LOOP))

    funcStatus = {}

    ## copy event to funcStatus
    funcStatus = event

    ## this is fatal
    if 'accountId' not in funcStatus:
        logger.error ("Error, we don't have an accountId")
        raise Exception ("no accountId was passed to function")

    ## check if we are in a loop, if not, initialize it
    if 'LoopCount' not in funcStatus:
        funcStatus['LoopCount'] = 0
    else:
        ## increment the counter
        funcStatus['LoopCount'] += 1
        
    if 'LoopAgain' not in funcStatus:
        funcStatus['LoopAgain'] = "yes"
        
    if 'funcState' not in funcStatus:
        funcStatus['funcState'] = "not complete"
        
    ## Define current date
    today = str(date.today())

    ## get the current account id and only assume role if what we are processing
    ## is different
    CurrentAccount = stsClient.get_caller_identity().get('Account')
    
    ## process the record
    logger.info("Processing AccountId: %s" % (funcStatus['accountId']))
    
    ## We need to switch to the correct account
    try:
        ## only switch roles if necessary
        if funcStatus['accountId'] != CurrentAccount:
            assumedRoleObject=stsClient.assume_role(
                RoleArn=f"arn:aws:iam::{funcStatus['accountId']}:role/{ASSUME_ROLE_NAME}",
                RoleSessionName="IAMCredentialReport")
            credentials=assumedRoleObject['Credentials']
    
            iamClient=boto3.client('iam',
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken'])
        else:
            iamClient=boto3.client('iam')
            
    except botocore.exceptions.ClientError as error:
        logger.error(error)
        raise error

    ## Generate report / check current state of report generation
    try:
        # Generate Credential Report
        reportcomplete = False
        gencredentialreport = iamClient.generate_credential_report()
        logger.info('IAM credential report current state: %s' % (gencredentialreport['State']))
        
        ## set true / false
        reportcomplete = gencredentialreport['State'] == 'COMPLETE'
        #reportcomplete = False  ## For testing

        if not reportcomplete:
            ###########################################################################        
            ## Error out if we have looped too many times
            ## The Step function will handle the error
            if funcStatus['LoopCount'] > int (MAX_LOOP):
                    logger.error ("Error: Too many iterations. Exceeded %s loops." % (MAX_LOOP))
                    funcStatus['ErrorMessage'] = f"Too many iterations. Exceeded MAX_LOOP of {MAX_LOOP}"
                    funcStatus['LoopAgain'] = "no"
                    funcStatus['funcState'] = "error"
                    return (funcStatus)
                    
            ## otherwise, loop
            else:
                logger.info ("Waiting for report to complete... Exiting to sleep in Step function.")
                funcStatus['LoopAgain'] = "yes"
                return (funcStatus)            


        ## report should be complete at this point
        logger.info('IAM credential report successfully generated for account Id: %s' % (funcStatus['accountId']))
        credentialReport = iamClient.get_credential_report()
        decodedCredentialReport = credentialReport['Content'].decode("utf-8")
        ## Save credential Report into CSV file
        funcStatus['reportFileName'] = f"credentialReport_{funcStatus['accountId']}.csv"
        
        # Write report to a temp file and upload to S3
        write_to_temp_and_upload(funcStatus['reportFileName'],decodedCredentialReport)
     
        ## everything should be done by this point
        funcStatus['LoopAgain'] = "no"
        funcStatus['funcState'] = "complete"        

        return (funcStatus)


    except iamClient.exceptions.LimitExceededException as error:
        logger.info ("Waiting for limit... Exiting to sleep in Step function.")
        funcStatus['LoopAgain'] = "yes"
        return (funcStatus) 

    except botocore.exceptions.ClientError as error:
        logger.error(error)
        raise error

    raise Exception ('Error, we should never be here, unknown code path.')

