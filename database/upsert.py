##
from __future__ import print_function
import json
import logging
import logging.config
import numpy as np
import os
import pandas as pd
import sys
import time
import yaml

from database.database_functions import (
    facebookconnect,
    bulk_upsert,
    find,
    extract_col,
    transform,
    get_request,
    request_to_database,
    batch_dates,
)
from datetime import datetime
from datetime import timedelta
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adsinsights import AdsInsights
from facebook_business.adobjects.adreportrun import AdReportRun
from facebook_business.adobjects.campaign import Campaign
from facebook_business.adobjects.adset import AdSet
from facebook_business.api import FacebookAdsApi
from facebook_business.exceptions import FacebookRequestError
from database.models import (
    mySQL_connect,
)
from sqlalchemy.orm import sessionmaker
#++++++++++++++++++++
# LOGGER
#++++++++++++++++++++

with open('database/config.yaml', 'r') as f:
    config = yaml.safe_load(f.read())
    logging.config.dictConfig(config)

logger = logging.getLogger(__name__)

#+++++++++++++++++++++++++++++++++++++
# | FACEBOOK AUTHENTICATION |
#+++++++++++++++++++++++++++++++++++++

secrets = 'database/settings/fb_client_secrets.json'
try:
    facebookconnect(secrets_path=secrets)
    logger.info('Facebook authentication was a success')
except Exception as e:
    logger.exception('Failed to connect to Facebook')

#+++++++++++++++++++++++++++++++++++++
# ENGINE CONNECTION
#+++++++++++++++++++++++++++++++++++++

credentials = 'database/settings/db_secrets.json'
try:
    engine = mySQL_connect(credentials, port='3306', db='acquire')
    logger.info('MySQL connection was a success')
except Exception as e:
    logger.exception('Failed to connect to MySQL')

#++++++++++++++++++++++++++++++++++++++++++
# | PARAMETERS FOR FACEBOOK API REQUESTS |
#++++++++++++++++++++++++++++++++++++++++++

# ACCOUNT
account_params = {'level': 'account'}
account_fields = [AdAccount.Field.account_id,
                  AdAccount.Field.name,
                  AdAccount.Field.account_status,
                  AdAccount.Field.currency,
                  AdAccount.Field.amount_spent,
                  ]
# CAMPAIGN
campaign_params = {'level': 'campaign',
                   'filtering': [{'field': 'campaign.effective_status',
                                 'operator': 'IN',
                                 'value': ['ACTIVE', 'PAUSED',
                                           'ARCHIVED', 'DELETED',
                                           'IN_PROCESS', 'WITH_ISSUES']}]}
campaign_fields = [Campaign.Field.id,
                   Campaign.Field.name,
                   Campaign.Field.account_id,
                   Campaign.Field.effective_status,
                   Campaign.Field.updated_time,
                   Campaign.Field.daily_budget,
                   ]
# AD SETS
adset_params = {'level': 'adset',
                'filtering': [{'field': 'adset.effective_status',
                               'operator': 'IN',
                               'value': ['ACTIVE', 'PAUSED',
                                         'ARCHIVED', 'DELETED',
                                         'IN_PROCESS', 'WITH_ISSUES',
                                         'PENDING_REVIEW', 'DISAPPROVED',
                                         'PREAPPROVED', 'PENDING_BILLING_INFO',
                                         'CAMPAIGN_PAUSED', 'ADSET_PAUSED']}]}
adset_fields = [AdSet.Field.id,
          AdSet.Field.name,
          AdSet.Field.account_id,
          AdSet.Field.campaign_id,
          AdSet.Field.created_time,
          AdSet.Field.daily_budget,
          AdSet.Field.status,
          AdSet.Field.optimization_goal,
          AdSet.Field.updated_time
          ]

# ADS
ads_params = {
    'time_increment': 1,
    'action_attribution_windows': ['1d_view', '7d_view',
                                   '28d_view', '1d_click',
                                   '7d_click', '28d_click'],
    'level': 'ad',
        }
ads_fields = [AdsInsights.Field.ad_id,
              AdsInsights.Field.account_id,
              AdsInsights.Field.campaign_id,
              AdsInsights.Field.adset_id,
              AdsInsights.Field.date_start,
              AdsInsights.Field.account_name,
              AdsInsights.Field.campaign_name,
              AdsInsights.Field.adset_name,
              AdsInsights.Field.ad_name,
              AdsInsights.Field.spend,
              AdsInsights.Field.account_currency,
              AdsInsights.Field.frequency,
              AdsInsights.Field.reach,
              AdsInsights.Field.impressions,
              AdsInsights.Field.actions,
              AdsInsights.Field.action_values,
              ]
# ADS - AGE AND GENDER
agegender_params = {
    'time_increment': 1,
    'level': 'ad',
    'action_attribution_windows': ['1d_view', '7d_view',
                                   '28d_view', '1d_click',
                                   '7d_click', '28d_click'],
    'breakdowns': ['age', 'gender'],
}

agegender_fields = [AdsInsights.Field.ad_id,
                    AdsInsights.Field.account_id,
                    AdsInsights.Field.campaign_id,
                    AdsInsights.Field.adset_id,
                    AdsInsights.Field.date_start,
                    AdsInsights.Field.account_name,
                    AdsInsights.Field.campaign_name,
                    AdsInsights.Field.adset_name,
                    AdsInsights.Field.ad_name,
                    AdsInsights.Field.spend,
                    AdsInsights.Field.account_currency,
                    AdsInsights.Field.frequency,
                    AdsInsights.Field.reach,
                    AdsInsights.Field.impressions,
                    AdsInsights.Field.actions,
                    AdsInsights.Field.action_values,
                    ]

# ADS - REGION
region_params = {
    'time_increment': 1,
    'level': 'ad',
    'action_attribution_windows': ['1d_view', '7d_view',
                                   '28d_view', '1d_click',
                                   '7d_click', '28d_click'],
    'breakdowns': ['region'],
}

region_fields = [AdsInsights.Field.ad_id,
                 AdsInsights.Field.account_id,
                 AdsInsights.Field.campaign_id,
                 AdsInsights.Field.adset_id,
                 AdsInsights.Field.date_start,
                 AdsInsights.Field.account_name,
                 AdsInsights.Field.campaign_name,
                 AdsInsights.Field.adset_name,
                 AdsInsights.Field.ad_name,
                 AdsInsights.Field.spend,
                 AdsInsights.Field.account_currency,
                 AdsInsights.Field.frequency,
                 AdsInsights.Field.reach,
                 AdsInsights.Field.impressions,
                 AdsInsights.Field.actions,
                 AdsInsights.Field.action_values,
                 ]
##
#+++++++++++++++++++++++++++++++++++++
# REQUESTS AND PUSHES
#+++++++++++++++++++++++++++++++++++++
##

def sleeper(seconds):
    """Puts the script to sleep for defined seconds
    """
    for i in range(seconds, 0, -1):
        sys.stdout.write(str(i)+' ')
        sys.stdout.flush()
        time.sleep(1)

# store a list of accounts that were synced and not synced properly
synced = []
not_synced = []

clients = [arg for arg in sys.argv]
clients = clients[1:]

#================================/////////////
#  BEGIN ITERATING OVER ACCOUNTS
#===============================/////////////
for account in clients: # account refers to an account name
    attempts = 3 # number of attempts while encountering request errors
    while attempts > 0:
        try:
            logger.info(f'Beginning to sync {account}')
            #==================
            # ACCOUNTS TABLE
            #==================
            account_request = get_request(account_id=account,
                                          table='accounts',
                                          params=account_params,
                                          fields=account_fields
                                          )
            request_to_database(request=account_request,
                                table='accounts',
                                engine=engine
                                )
            logging.info("Accounts Table successfully synced to database")
            #===================
            # CAMPAIGNS TABLE
            #===================
            campaign_request = get_request(account_id=account,
                                           table='campaigns',
                                           params=campaign_params,
                                           fields=campaign_fields
                                           )
            request_to_database(request=campaign_request,
                                table='campaigns',
                                engine=engine
                                )
            logging.info("Campaigns Table successfully synced to database")
            #================
            # AD SETS TABLE
            #================
            adsets_request = get_request(account_id=account,
                                         table='adsets',
                                         params=adset_params,
                                         fields=adset_fields
                                         )

            request_to_database(request=adsets_request,
                                table='adsets',
                                engine=engine
                                )
            logging.info("Ad Sets Table successfully synced to database")
            sleeper(60) # WAIT 1 MINUTE
            #=====================
            # ADS INSIGHTS TABLE
            #=====================
            # define an interval for batching with smaller date ranges:
            intv = 12
            end = datetime.strftime(datetime.now() - \
                                    timedelta(days=1), "%Y-%m-%d")
            start = datetime.strftime(datetime.now() - \
                                      timedelta(days=60), "%Y-%m-%d")
            # store the list of dictionaries defining date params
            time_ranges = batch_dates(start, end, intv)

            for i in range(intv):
                time_range = time_ranges[i]
                ads_params['time_range'] = time_range
                logging.info(f"batching from date range: {time_range['since']} - {time_range['until']}")
                ads_request = get_request(account_id=account,
                                          table='ads_insights',
                                          params=ads_params,
                                          fields=ads_fields
                                          )
                request_to_database(request=ads_request,
                                    table='ads_insights',
                                    engine=engine
                                    )
                logging.info(f"batch success; {i+1} out of {intv}")
                sleeper(30)
            logging.info("Ads Insights Table successfully synced to database")
            #======================
            # AGE AND GENDER TABLE
            #======================
            for i in range(intv):
                time_range = time_ranges[i]
                agegender_params['time_range'] = time_range
                logging.info(f"batching from date range: {time_range['since']} - {time_range['until']}")
                agegender_request = get_request(account_id=account,
                                                table='ads_insights_age_and_gender',
                                                params=agegender_params,
                                                fields=agegender_fields
                                                )
                request_to_database(request=agegender_request,
                                    table='ads_insights_age_and_gender',
                                    engine=engine
                                    )
                logging.info(f"batch success; {i+1} out of {intv}")
                # WAIT 1 MINUTE
                sleeper(60)
            logging.info("Ads-Age and Gender Table successfully synced to database")

            # WAIT 10 MINUTES BETWEEN THESE TWO LARGE TABLES
            sleeper(600)
            #==================
            # REGION TABLE
            #==================
            # This table is often the biggest batch of api requests and so
            # has a greater frequency of errors. Most often - too many calls
            # from a single ad account.
            for i in range(intv):
                # do not sync regions table for muse (too large)
                if (account == 'muse') or (account == 'sheertex'):
                    break
                tries = 2 # gives this table 1 retry after a half hour wait
                while tries > 0:
                    try:
                        time_range = time_ranges[i]
                        region_params['time_range'] = time_range
                        logging.info(f"batching from date range: {time_range['since']} - {time_range['until']}")
                        region_request = get_request(account_id=account,
                                                 table='ads_insights_region',
                                                 params=region_params,
                                                 fields=region_fields
                                                 )
                        request_to_database(request=region_request,
                                            table='ads_insights_region',
                                            engine=engine
                                            )
                        logging.info(f"batch success; {i+1} out of {intv}")
                        # WAIT 3 MINUTE
                        sleeper(120)
                    except FacebookRequestError as e:
                        logger.exception('Encountered an error - waiting 30 minutes...')
                        tries -= 1
                        sleeper(1800) # wait 30 minutes
                        continue
                    break
            logging.info("Ads-Region Table successfully synced to database")
            #===================
            # END OF REQUESTS 
            #===================
            logger.info(f'CODE_200: Completed syncing {account} to database!')
            synced.append(account)
        # Catching request errors from any other table and retrying the entire account
        # 2 more times...
        except FacebookRequestError as e:
            logger.exception(f'Encountered an error - retrys remaining: {attempts - 1}')
            attempts -= 1
            if attempts == 0:
                logger.warning(f'not able to finish syncing {account}')
                not_synced.append(account) # storing accounts that were not successfull
            continue
        break
# return all accounts not syned properly
synced_string = ",".join(synced)
not_synced_string = ",".join(not_synced)
synced_message = "The following accounts were synced: "
not_synced_message = "The following accounts were not properly synced: "
if len(not_synced) > 0: # if at least 1 account not synced properly - display
    logging.warning(f'{not_synced_message} {not_synced_string}')
logging.info(f'{synced_message} {synced_string}')


