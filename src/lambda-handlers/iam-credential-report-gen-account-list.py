####################################################################
##  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
##  SPDX-License-Identifier: MIT-0
####################################################################
##  iam-credential-report-account-list
##
##      input fields
##          none
##
##      output fields
##          listedAccounts :    an array of "accountId" values that are 
##                              in the organization and are not in a 
##                              suspended state.
##

import os
import boto3
import logging
import sys

from botocore.exceptions import ClientError
from datetime import date

logger = logging.getLogger(__name__)
logger.setLevel(level=logging.INFO)  # use level DEBUG for more details

## Define Organization client
orgClient = boto3.client('organizations')

###############################################################################

def lambda_handler(event, context):
    
    ## Used to track how many accounts were found
    AccountsSent = 0
    AccountsTotal = 0
        
    ## to return the list of account IDs
    AccountList = []

    ## control the loop
    done = False
    
    ## set the max results, 20 is the limit for the list_accounts function
    MaxResultsVal=20
    
    ## intialize the return variable
    listedAccounts = {}

    ## if there are more than MaxResult Accounts, we need to loop
    while not done:
        
        ## Get the list of accounts
        try:
            ## if there are more than MaxResults, than the listedAccounts will have NextToken set
            ## so call the list_accounts again using the NextToken value
            if 'NextToken' in listedAccounts:
                listedAccounts = orgClient.list_accounts(MaxResults = MaxResultsVal, NextToken = listedAccounts['NextToken'])
                
            ## This is the first time through the loop, so no NextToken
            else:
                listedAccounts = orgClient.list_accounts(MaxResults = MaxResultsVal)
                
        except ClientError as error:
            logger.error(error)
            raise error
            
        ## Need to control breaking out of the while loop
        ## if there is no more records, exit the loop
        if not 'NextToken' in listedAccounts:
            done = True


        ## loop through all the accounts and look
        for account in listedAccounts['Accounts']:
            
            ## format the value to send
            accountId = { "accountId" : account['Id']}
            
            ## track the count
            AccountsTotal += 1
            ## don't look at suspended accounts
            if account['Status'] != 'SUSPENDED':
                AccountsSent += 1
                logger.info ("Account: %s" % (accountId['accountId']))
                AccountList.append(accountId)
            

    logger.info ("Completed! Sent %i active accounts out of %i total accounts to Step Function." % (AccountsSent,AccountsTotal))

    return(AccountList)

