#!/usr/bin/env python

# AWS Batch Cost Estimator
#
# Reads input CMDB information from a traditional data center to size and cost estimate AWS EC2 & RDS
# infrastructure.
#
# Prerequisites:
# 1. Python
# 2. AWS Python SDK (Boto3)
# 3. Pandas Python library
# 4. json Python library
# 5. re Python libary

# Load libraries
import pandas as pd
import json
import boto3
import re

# Configuration variables
fileInput='~/inputdata/cmdb.csv'
fileOutput='~/outputdata/aws_bom.csv'

# Input column mappings

# Column which indicates source cores and peak load
srcCores = 'CPU'
srcCPUUsage = 'Peak CPU Load'

# Column which indicates peak memory useage in GB
# If srcMemUsed is blank or zero, the script will use srcMemProvsioned as the target memory
srcMemProvisioned = 'Mem (GB)'
srcMemUsed = 'Peak Mem Used'

# Columns indicating environment (dev, test, prod, etc.)
srcEnv = 'Current State Services'
DEV = 'Dev'
QA = 'QA'
TEST = 'Test'

# Region mappings, including using a default region if not specified as europe or asia
srcRegion='Target Region'
srcASIA="AP"
awsASIA="ap-northeast-2"
srcEU='EU'
awsEU='eu-central-1'
awsDFLT='us-east-1'
awsLocDFLT="US East (N. Virginia)"
awsLocEU="EU (Frankfurt)"
awsLocASIA="Asia Pacific (Seoul)"

# OS platforms for AWS.  The customer source is all over the board and requires some manual
# tweaking.  So far only coded for Windows, RHEL, and Amazon Linux (default)
srcOS='Platform'
srcOSVer='OS Ver'
awsWindows="Windows"
awsRHEL="RHEL"
awsDefault="Linux"

# Compute families.  These are super families.  X and T are actually subfamilies in the pricing API
awsComputeOptimized="Compute optimized"
awsMemoryOptimized="Memory optimized"
awsGeneralPurpose="General purpose"

# Database mappings

# Column which determines if a configuration item is an RDS candidate
# Non zero value in this column indicates a database present
srcDbInstanceCount = 'DB Instance Count'

# Dataase constants
srcOracle="Oracle"
srcSQLServer="SQL "
srcDB="DB Rel/Ver"
awsOracle="Oracle"
awsSQLServer="SQL Server"
awsAurora="Aurora MySQL"

# Fixed rates for block storage
ec2EBSUnitCost=.151
rdsEBSUnitCost=.116
srcBlockStorage='Fixed Used Size (GB)'

# Open input file, read into frame
print("Reading input file....")
dfCMDB = pd.read_csv(fileInput, keep_default_na=False)

#Add RDS Column
print("Determining RDS targets....")
dfCMDB['RDS']=False

# List the servers with database instances along with type, flag as targets for RDS service
dfDBServers = dfCMDB[dfCMDB[srcDbInstanceCount] != ""]
dfDBServers = dfDBServers[dfDBServers[srcDbInstanceCount] !="0"]

indexes=dfDBServers.index.tolist()

for row in indexes:
    dfCMDB.loc[row, 'RDS'] = True
    
# Calculate cores needed from peak CPU
print("Calculating target EC2 cores...")
dfCMDB['cores_calc'] = (dfCMDB[srcCores] * dfCMDB[srcCPUUsage]) + .51
dfCMDB['cores_calc']=dfCMDB['cores_calc'].round(decimals=0)

# Correct missing used memory
for index in dfCMDB.index.tolist():
    if dfCMDB.loc[index, srcMemUsed] == 0:
        dfCMDB.loc[index, srcMemUsed] = dfCMDB.loc[index, srcMemProvisioned]
        
# Create family inference column
print("Determining EC2 instance families...")
dfCMDB['calc_family'] = ""

# Make an inference for ec2 family
dfCMDB['mem_cpu_ratio'] = dfCMDB[srcMemUsed] / dfCMDB['cores_calc']

for index in dfCMDB.index.tolist():
    if ((dfCMDB.loc[index, 'cores_calc'] <= 8) and (dfCMDB.loc[index, srcMemUsed] <=32)
        and (DEV in dfCMDB.loc[index, srcEnv]
             or QA in dfCMDB.loc[index, srcEnv]
             or TEST in dfCMDB.loc[index, srcEnv])):
            dfCMDB.loc[index, 'calc_family'] = "t"
            
    elif (dfCMDB.loc[index, 'mem_cpu_ratio'] < 3.5):
             dfCMDB.loc[index, 'calc_family'] = "c"
            
    elif (dfCMDB.loc[index, 'mem_cpu_ratio'] > 4.5):
             dfCMDB.loc[index, 'calc_family'] = "r"
            
    else:
             dfCMDB.loc[index, 'calc_family'] = "m"
            

            
# Create AWS Region Column and map to source region
# ap-northeast-2
# us-east-1
# eu-central-1
dfCMDB['AWS_Region'] = ""

print ("Mapping regions...")

for index in dfCMDB.index.tolist():
    if dfCMDB.loc[index, srcRegion] == srcASIA:
        dfCMDB.loc[index, 'AWS_Region'] = awsASIA
    elif dfCMDB.loc[index, srcRegion] == srcEU:
        dfCMDB.loc[index, 'AWS_Region'] = awsEU
    else:
        dfCMDB.loc[index, 'AWS_Region'] = awsDFLT
        
# Create AWS OS column, search for key words in source os to map to EC2 platform

print ("Determining OS platforms...")
dfCMDB['AWS_OS'] = ""

# This code required manual tweaking to account for the different representations of RedHat
for index in dfCMDB.index.tolist():
    if "Windows" in dfCMDB.loc[index, srcOS]:
        dfCMDB.loc[index, 'AWS_OS'] = awsWindows
    elif "Linux" in dfCMDB.loc[index, srcOS]:
        if ("RHEL" in dfCMDB.loc[index, srcOSVer] or
            "Red" in dfCMDB.loc[index, srcOSVer] or
            "RED" in dfCMDB.loc[index, srcOSVer]):
                dfCMDB.loc[index, 'AWS_OS'] = awsRHEL
        else:
            dfCMDB.loc[index, 'AWS_OS'] = awsDefault
    else:
        dfCMDB.loc[index, 'AWS_OS'] = awsDefault
        
# Core matching and pricing code
# Match calculated capacity requirements to EC2 instance types
# Price resulting EC2 instance types by hour, year, and 3-year RIs

print('Pricing EC2 instances....')

# Core matching and pricing code
# Match calculated capacity requirements to EC2 instance types
# Price resulting EC2 instance types by hour, year, and 3-year RIs

regions = {awsDFLT, awsEU, awsASIA}
families = {"m", "c", "r", "t"}
oses = {awsWindows, awsRHEL, awsDefault}

for region in regions:
    print("Region " +region)
    for os in oses:
        print("OS " + os)
        for family in families:
            print("Family " +family)
            # Lets get specific and only get the license included, no pre-installed software, current generation, etc.
            client = boto3.client('pricing')
            
            if region == awsDFLT:
                location = awsLocDFLT
            elif region == awsEU:
                location = awsLocEU
            else:
                location = awsLocASIA
            
            if family == "c":
                instanceFamily = awsComputeOptimized
            elif family == "r":
                instanceFamily = awsMemoryOptimized
            else:
                instanceFamily = awsGeneralPurpose
    
            response = client.get_products(
                Filters=[
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'location',
                        'Value': location
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'operatingSystem',
                        'Value': os
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'instanceFamily',
                        'Value': instanceFamily
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'currentGeneration',
                        'Value': 'Yes'
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'licenseModel',
                        'Value': 'No License required'
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'tenancy',
                        'Value': 'Shared'
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'preInstalledSw',
                        'Value': 'NA'
                    }
                ],
                ServiceCode='AmazonEC2',
                MaxResults=100
            )
        
            # Let's parse the JSON and get the elements we need to map to EC2 instance type
            items=response['PriceList']


            # Lets make a dataframe with the EC2 instance choices that are rhel and memory optimized
            d={'instanceType':[], 'memory':[], 'family':[], 'one_hr_rate':[], 'one_yr_rate':[], 'three_yr_rate':[], 'vcpu':[]}
            dfInstanceList=pd.DataFrame(data=d)
            index=0

            for item in items:
                skip = False
                jItem=json.loads(item)
                itemAttributes=jItem['product']['attributes']
                instanceType=itemAttributes['instanceType']
                instancefamily=instanceType[0:2]
                
                # Filter out the new m5d types
                if (instanceType[0:3] == "m5d"):
                    skip = True
                
                if ((instancefamily != "c3") and (instancefamily != "m3") and (skip != True)):
                    vcpu=itemAttributes['vcpu']
                    sku=jItem['product']['sku']
                    ondemandterm="JRTCKXETXF"
                    ondemandratecode="6YS6EN2CT7"
                    oneyearterm="6QCMYABX3D"
                    oneyearratecode="2TG2D8R56U"
                    threeyearterm="NQ3QZPMQV9"
                    threeyearratecode="2TG2D8R56U"
                    onehr_rate=jItem['terms']['OnDemand'][sku+"."+ondemandterm]['priceDimensions'][sku+"."+ondemandterm+"."+ondemandratecode]['pricePerUnit']['USD']
                    oneyr_rate=jItem['terms']['Reserved'][sku+"."+oneyearterm]['priceDimensions'][sku+"."+oneyearterm+"."+oneyearratecode]['pricePerUnit']['USD']
                    threeyr_rate=jItem['terms']['Reserved'][sku+"."+threeyearterm]['priceDimensions'][sku+"."+threeyearterm+"."+threeyearratecode]['pricePerUnit']['USD']
                
                # Drop the old lines
                if (family == "t"):
                    if (instancefamily[0] != "m"):
                        memoryelement=itemAttributes['memory']
                        memory=re.sub('[^0-9]','', memoryelement)
                        dfInstanceList.loc[index, 'instanceType'] = itemAttributes['instanceType']
                        dfInstanceList.loc[index, 'memory'] =  memory
                        dfInstanceList.loc[index,'family'] = family
                        dfInstanceList.loc[index, 'vcpu'] = vcpu 
                        dfInstanceList.loc[index, 'one_hr_rate'] = onehr_rate
                        dfInstanceList.loc[index, 'one_yr_rate'] = oneyr_rate
                        dfInstanceList.loc[index, 'three_yr_rate'] = threeyr_rate
                        index=index+1


                elif (region == awsDFLT):
                    if ((instancefamily != "m4") and (instancefamily != "m3") and (instancefamily != "c4") and (instancefamily !="c3") and (instancefamily != "r3") and (instancefamily != "t2") and (skip != True)):
                        
                        #strip out the nasty characters from the json memory field
                        memoryelement=itemAttributes['memory']
                        memoryelement_strip = memoryelement.replace(' GiB','')
                        memoryelement_strip = memoryelement_strip.split(".")[0]
                        memory=re.sub('[^0-9]','', memoryelement_strip)
                        
                        dfInstanceList.loc[index, 'instanceType'] = itemAttributes['instanceType']
                        dfInstanceList.loc[index, 'memory'] =  memory
                        dfInstanceList.loc[index,'family'] = family
                        dfInstanceList.loc[index,'vcpu'] = vcpu
                        dfInstanceList.loc[index, 'one_hr_rate'] = onehr_rate
                        dfInstanceList.loc[index, 'one_yr_rate'] = oneyr_rate
                        dfInstanceList.loc[index, 'three_yr_rate'] = threeyr_rate
                        index=index+1

                else:
                    if ((instancefamily != "m3") and (instancefamily != "c3") and (instancefamily != "r3") and (instancefamily != "t2") and (skip != True)):
                        memoryelement=itemAttributes['memory']
                        
                        #strip out the nasty characters from the json memory field
                        memoryelement_strip = memoryelement.replace(' GiB','')
                        memoryelement_strip = memoryelement_strip.split(".")[0]
                        memory=re.sub('[^0-9]','', memoryelement_strip)
                        
                        dfInstanceList.loc[index, 'instanceType'] = itemAttributes['instanceType']
                        dfInstanceList.loc[index, 'memory'] =  memory
                        dfInstanceList.loc[index,'family'] = family
                        dfInstanceList.loc[index, 'vcpu'] = vcpu
                        dfInstanceList.loc[index, 'one_hr_rate'] = onehr_rate
                        dfInstanceList.loc[index, 'one_yr_rate'] = oneyr_rate
                        dfInstanceList.loc[index, 'three_yr_rate'] = threeyr_rate
                        index=index+1
                        
            skip = False
            
            #Convert elements to numeric
            dfInstanceList['memory']=dfInstanceList['memory'].apply(pd.to_numeric)
            dfInstanceList['vcpu']=dfInstanceList['vcpu'].apply(pd.to_numeric)
            dfInstanceList['one_hr_rate']=dfInstanceList['one_hr_rate'].apply(pd.to_numeric)
            dfInstanceList['one_yr_rate']=dfInstanceList['one_yr_rate'].apply(pd.to_numeric)
            dfInstanceList['three_yr_rate']=dfInstanceList['three_yr_rate'].apply(pd.to_numeric)

            #If memory optimzied sort primary by memory, otherwise sort primary by CPU
            if(family == "r"):
                dfInstanceList_sorted=dfInstanceList.sort_values(['memory', 'vcpu'], ascending=[True,True])
            else:
                dfInstanceList_sorted=dfInstanceList.sort_values(['vcpu', 'memory'], ascending=[True,True])
            
            dfInstanceList_sorted=dfInstanceList_sorted.reset_index(drop=True)
                    
            dfCMDB_filter = dfCMDB[(dfCMDB.calc_family == family) & (dfCMDB.AWS_OS == os) & (dfCMDB.RDS == False) & (dfCMDB.AWS_Region == region)]

            # Map instances to EC2 instance types  

            for index in dfCMDB_filter.index.tolist():
                found=False
                instance=0

                while ((not(found)) & (instance < len(dfInstanceList_sorted))):
                    if ((dfInstanceList_sorted.loc[instance, 'memory'] >= dfCMDB.loc[index, srcMemUsed]) and (dfInstanceList_sorted.loc[instance, 'vcpu'] >= dfCMDB.loc[index, 'cores_calc'])):
                        found = True
                        dfCMDB.loc[index, 'ec2_instance_type'] = dfInstanceList_sorted.loc[instance, 'instanceType']
                        dfCMDB.loc[index, 'one_hr_rate'] = dfInstanceList_sorted.loc[instance, 'one_hr_rate']
                        dfCMDB.loc[index, 'one_yr_rate'] = dfInstanceList_sorted.loc[instance, 'one_yr_rate']
                        dfCMDB.loc[index, 'three_yr_rate'] = dfInstanceList_sorted.loc[instance, 'three_yr_rate']
                        
                    instance = instance +1
                    
                    
# Review and price RDS                    
# Map source DB to AWS_DB

dfCMDB['AWS_DB'] = "" 
dfCMDB_filterrds = dfCMDB[(dfCMDB.RDS == True)]   
   
indexes=dfCMDB_filterrds.index.tolist()
for row in indexes:
    if srcOracle in dfCMDB.loc[row, srcDB]:
        dfCMDB.loc[row, 'AWS_DB'] = awsOracle
    elif srcSQLServer in dfCMDB.loc[row, srcDB]:
        dfCMDB.loc[row, 'AWS_DB'] = awsSQLServer
    else:
        dfCMDB.loc[row, 'AWS_DB'] = awsAurora
        
# Map RDS instances
#regions = {"us-east-1", "eu-central-1", "ap-northeast-2"}
#families = {"m", "c", "r", "t"}
dbs = {awsOracle, awsSQLServer, awsAurora}

print('Pricing RDS...')

for region in regions:
    print('Region ' + region)
    for db in dbs:
        print('DB ' + db)
        for family in families:
            print('Family ' + family)
            # Lets get specific and only get the license included, no pre-installed software, current generation, etc.
            client = boto3.client('pricing')
            
            if region == awsDFLT:
                location = awsLocDFLT
            elif region == awsEU:
                location = awsLocEU
            else:
                location = awsLocASIA
            
            if family == "r":
                instanceFamily = awsMemoryOptimized
            else:
                instanceFamily = awsGeneralPurpose
                
            if db == awsAurora:
                licensemodel="No license required"
                instanceFamily = awsMemoryOptimized
            else:
                licensemodel="License included"
    
            response = client.get_products(
                Filters=[
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'location',
                        'Value': location
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'databaseEngine',
                        'Value': db
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'currentGeneration',
                        'Value': 'Yes'            
                    },
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'instanceFamily',
                        'Value': instanceFamily          
                    },      
                    {
                        'Type': 'TERM_MATCH',
                        'Field': 'licenseModel',
                        'Value': licensemodel            
                    }, 
                    ],                
                    ServiceCode='AmazonRDS',
                    MaxResults=100
                )
        
            # Let's parse the JSON and get the elements we need to map to EC2 instance type
            items=response['PriceList']

            # Lets make a dataframe with the RDS instance choices
            d={'instanceType':[], 'memory':[], 'family':[], 'one_hr_rate':[], 'one_yr_rate':[], 'three_yr_rate':[], 'vcpu':[]}
            dfInstanceList=pd.DataFrame(data=d)
            index=0

            for item in items:
                jItem=json.loads(item)
                itemAttributes=jItem['product']['attributes']
                instanceType=itemAttributes['instanceType']
                instancefamily=instanceType[3:5]
                vcpu=itemAttributes['vcpu']
                sku=jItem['product']['sku']
                ondemandterm="JRTCKXETXF"
                ondemandratecode="6YS6EN2CT7"
                
                if (db == awsSQLServer):
                    oneyearterm="HU7G6KETJZ"
                else:
                    oneyearterm="6QCMYABX3D"
                
                oneyearratecode="2TG2D8R56U"
                onyearratecode="6YS6EN2CT7"
                threeyearterm="NQ3QZPMQV9"
                threeyearratecode="2TG2D8R56U"
                onehr_rate=jItem['terms']['OnDemand'][sku+"."+ondemandterm]['priceDimensions'][sku+"."+ondemandterm+"."+ondemandratecode]['pricePerUnit']['USD']
                oneyr_rate=jItem['terms']['Reserved'][sku+"."+oneyearterm]['priceDimensions'][sku+"."+oneyearterm+"."+oneyearratecode]['pricePerUnit']['USD']
                
                # Account for the absence of an 'one-year all up-front' option for SQL server
                if db == awsSQLServer:  
                    sqlhourly=float(jItem['terms']['Reserved'][sku+"."+oneyearterm]['priceDimensions'][sku+"."+oneyearterm+"."+ondemandratecode]['pricePerUnit']['USD'])
                    oneyr_rate = float(oneyr_rate) + (sqlhourly * 8760)

                threeyr_rate=jItem['terms']['Reserved'][sku+"."+threeyearterm]['priceDimensions'][sku+"."+threeyearterm+"."+threeyearratecode]['pricePerUnit']['USD']
           
                # person = input('Enter your name: ')
        
                # Load rates
                memoryelement=itemAttributes['memory']
                        
                #strip out the nasty characters from the json memory field
                memoryelement_strip = memoryelement.replace(' GiB','')
                memoryelement_strip = memoryelement_strip.split(".")[0]
                memory=re.sub('[^0-9]','', memoryelement_strip)

                dfInstanceList.loc[index, 'instanceType'] = itemAttributes['instanceType']
                dfInstanceList.loc[index, 'memory'] =  memory
                dfInstanceList.loc[index,'family'] = family
                dfInstanceList.loc[index, 'vcpu'] = vcpu 
                dfInstanceList.loc[index, 'one_hr_rate'] = onehr_rate
                dfInstanceList.loc[index, 'one_yr_rate'] = oneyr_rate
                dfInstanceList.loc[index, 'three_yr_rate'] = threeyr_rate
                index=index+1
            
            #Convert elements to numeric
            
            dfInstanceList['memory']=dfInstanceList['memory'].apply(pd.to_numeric)
            dfInstanceList['vcpu']=dfInstanceList['vcpu'].apply(pd.to_numeric)
            dfInstanceList['one_hr_rate']=dfInstanceList['one_hr_rate'].apply(pd.to_numeric)
            dfInstanceList['one_yr_rate']=dfInstanceList['one_yr_rate'].apply(pd.to_numeric)
            dfInstanceList['three_yr_rate']=dfInstanceList['three_yr_rate'].apply(pd.to_numeric)

            # If family is memory optimized, sorty primarily by memory, otherwise primarly cpu
            if(family == "r"):
                dfInstanceList_sorted=dfInstanceList.sort_values(['memory', 'vcpu'], ascending=[True,True])
            else:
                dfInstanceList_sorted=dfInstanceList.sort_values(['vcpu', 'memory'], ascending=[True,True])

            dfInstanceList_sorted=dfInstanceList_sorted.reset_index(drop=True)
            
            myregion=region
                    
            dfCMDB_filter = dfCMDB[(dfCMDB.calc_family == family) & (dfCMDB.AWS_DB == db) & (dfCMDB.RDS == True) & (dfCMDB.AWS_Region == myregion)]

            
            # Map instances to EC2 instance types  
            for index in dfCMDB_filter.index.tolist():
                found=False
                instance=0
                
                while ((not(found)) & (instance < len(dfInstanceList_sorted))):
                    if ((dfInstanceList_sorted.loc[instance, 'memory'] >= dfCMDB.loc[index, 'Peak Mem Used']) and (dfInstanceList_sorted.loc[instance, 'vcpu'] >= dfCMDB.loc[index, 'cores_calc'])):
                        found = True
                        dfCMDB.loc[index, 'ec2_instance_type'] = dfInstanceList_sorted.loc[instance, 'instanceType']
                        dfCMDB.loc[index, 'one_hr_rate'] = dfInstanceList_sorted.loc[instance, 'one_hr_rate']
                        dfCMDB.loc[index, 'one_yr_rate'] = dfInstanceList_sorted.loc[instance, 'one_yr_rate']
                        dfCMDB.loc[index, 'three_yr_rate'] = dfInstanceList_sorted.loc[instance, 'three_yr_rate']

                    instance = instance +1
                    
# Compute EBS and snapshots
dfCMDB['ebs_month_rate'] = 0
print('Pricing EBS and snapshots...')

# Flat storage rates assuming 1% monthly rate of change on EC2

for index in dfCMDB.index.tolist():
    if dfCMDB.loc[index, 'RDS'] == True:
        dfCMDB.loc[index, 'ebs_month_rate'] = dfCMDB.loc[index, srcBlockStorage] * rdsEBSUnitCost
    else:
        dfCMDB.loc[index, 'ebs_month_rate'] = dfCMDB.loc[index, srcBlockStorage] * ec2EBSUnitCost

# Write output file
print("Writing output file...")
dfCMDB.to_csv(fileOutput)
