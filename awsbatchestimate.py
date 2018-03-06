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
# 5. re Pythong libary

# Load libraries
import pandas as pd
import json
import boto3
import re

# Initialize variables
fileInput='cmdb.csv'

# Open input file, read into frame
print("Reading input file....")
dfCMDB = pd.read_csv(fileInput, keep_default_na=False)

#Add RDS Column
print("Determining RDS targets....")
dfCMDB['RDS']=False

# List the servers with database instances along with type, flag as targets for RDS service
dfDBServers = dfCMDB[dfCMDB['DB Instance Count'] != ""]
dfDBServers = dfDBServers[dfDBServers['DB Instance Count'] !="0"]
dfDBServers[['Node Name', 'DB Rel/Ver','Target Region', 'Resilliency / DR Classification']]

indexes=dfDBServers.index.tolist()

for row in indexes:
    dfCMDB.loc[row, 'RDS'] = True
    
# Calculate cores needed from peak CPU
print("Calculating target EC2 cores...")
dfCMDB['cores_calc'] = (dfCMDB['CPU'] * dfCMDB['Peak CPU Load']) + .51
dfCMDB['cores_calc']=dfCMDB['cores_calc'].round(decimals=0)

# Correct missing peak memory
for index in dfCMDB.index.tolist():
    if dfCMDB.loc[index, 'Peak Mem Used'] == 0:
        dfCMDB.loc[index, 'Peak Mem Used'] = dfCMDB.loc[index, 'Mem (MB)'] / 1000
        
# Create family inference column
print("Determining EC2 instance families...")
dfCMDB['calc_family'] = ""


# Make an inference for ec2 family
dfCMDB['mem_cpu_ratio'] = dfCMDB['Peak Mem Used'] / dfCMDB['cores_calc']

for index in dfCMDB.index.tolist():
    if ((dfCMDB.loc[index, 'cores_calc'] <= 8) and (dfCMDB.loc[index, 'Peak Mem Used'] <=32)
        and ("Dev" in dfCMDB.loc[index, 'Current State Services']
             or "QA" in dfCMDB.loc[index, 'Current State Services']
             or "Test" in dfCMDB.loc[index, 'Current State Services'])):
            dfCMDB.loc[index, 'calc_family'] = "t"
            
    elif (dfCMDB.loc[index, 'mem_cpu_ratio'] < 3.5):
             dfCMDB.loc[index, 'calc_family'] = "c"
            
    elif (dfCMDB.loc[index, 'mem_cpu_ratio'] > 4.5):
             dfCMDB.loc[index, 'calc_family'] = "r"
            
    else:
             dfCMDB.loc[index, 'calc_family'] = "m"
            
# Create AWS Region Column and map to source region
# ap-southeast-1
# us-east-1
# eu-central-1
dfCMDB['AWS_Region'] = ""

print ("Mapping regions...")

for index in dfCMDB.index.tolist():
    if dfCMDB.loc[index, 'Target Region'] == "AP":
        dfCMDB.loc[index, 'AWS_Region'] = "ap-southeast-1"
    elif dfCMDB.loc[index, 'Target Region'] == "EU":
        dfCMDB.loc[index, 'AWS_Region'] = "eu-central-1"
    else:
        dfCMDB.loc[index, 'AWS_Region'] = "us-east-1"
        
# Create AWS OS column, search for key words in source os to map to EC2 platform

print ("Determining OS platforms...")
dfCMDB['AWS_OS'] = ""

for index in dfCMDB.index.tolist():
    if "WINDOWS" in dfCMDB.loc[index, 'Platform']:
        dfCMDB.loc[index, 'AWS_OS'] = "Windows"
    elif "LINUX" in dfCMDB.loc[index, 'Platform']:
        if ("RHEL" in dfCMDB.loc[index, 'OS Ver'] or
            "Red" in dfCMDB.loc[index, 'OS Ver'] or
            "RED" in dfCMDB.loc[index, 'OS Ver']):
                dfCMDB.loc[index, 'AWS_OS'] = "RHEL"
        else:
            dfCMDB.loc[index, 'AWS_OS'] = "Linux"
    else:
        dfCMDB.loc[index, 'AWS_OS'] = "Linux"
        
# Core matching and pricing code
# Match calculated capacity requirements to EC2 instance types
# Price resulting EC2 instance types by hour, year, and 3-year RIs

print('Pricing EC2 instances....')

regions = {"us-east-1", "eu-central-1", "ap-southeast-1"}
families = {"m", "c", "r", "t"}
oses = {"Windows", "RHEL", "Linux"}

for region in regions:
    print('Pricing ' + region)
    for os in oses:
        print('Pricing ' + os)
        for family in families:
            print('Pricing ' + family)
            # Lets get specific and only get the license included, no pre-installed software, current generation, etc.
            client = boto3.client('pricing')
            
            if region == "us-east-1":
                location = "US East (N. Virginia)"
            elif region == "eu-central-1":
                location = "EU (Frankfurt)"
            else:
                location = "Asia Pacific (Singapore)"
            
            if family == "c":
                instanceFamily = "Compute optimized"
            elif family == "r":
                instanceFamily = "Memory optimized"
            else:
                instanceFamily = "General purpose"
    
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
            d={'instanceType':[], 'memory':[], 'family':[], 'one_hr_rate':[], 'one_yr_rate':[], 'three_yr_rate':[]}
            dfInstanceList=pd.DataFrame(data=d)
            index=0

            for item in items:
                jItem=json.loads(item)
                itemAttributes=jItem['product']['attributes']
                instanceType=itemAttributes['instanceType']
                instancefamily=instanceType[0:2]
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


                elif (region == "us-east-1"):
                    if ((instancefamily != "m4") and (instancefamily != "m3") and (instancefamily != "c4") and (instancefamily !="c3") and (instancefamily != "r3") and (instancefamily != "t2")):
                        memoryelement=itemAttributes['memory']
                        memory=re.sub('[^0-9]','', memoryelement)
                        dfInstanceList.loc[index, 'instanceType'] = itemAttributes['instanceType']
                        dfInstanceList.loc[index, 'memory'] =  memory
                        dfInstanceList.loc[index,'family'] = family
                        dfInstanceList.loc[index,'vcpu'] = vcpu
                        dfInstanceList.loc[index, 'one_hr_rate'] = onehr_rate
                        dfInstanceList.loc[index, 'one_yr_rate'] = oneyr_rate
                        dfInstanceList.loc[index, 'three_yr_rate'] = threeyr_rate
                        index=index+1

                else:
                    if ((instancefamily != "m3") and (instancefamily != "c3") and (instancefamily != "r3") and (instancefamily != "t2")):
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
            
            #Convert memory to numeric
            dfInstanceList['memory']=dfInstanceList['memory'].apply(pd.to_numeric)
            dfInstanceList['vcpu']=dfInstanceList['vcpu'].apply(pd.to_numeric)
            dfInstanceList['one_hr_rate']=dfInstanceList['one_hr_rate'].apply(pd.to_numeric)
            dfInstanceList['one_yr_rate']=dfInstanceList['one_yr_rate'].apply(pd.to_numeric)
            dfInstanceList['three_yr_rate']=dfInstanceList['three_yr_rate'].apply(pd.to_numeric)

            dfInstanceList_sorted=dfInstanceList.sort_values(by=['vcpu'], ascending=True)
            dfInstanceList_sorted=dfInstanceList_sorted.reset_index(drop=True)
                    
            dfCMDB_filter = dfCMDB[(dfCMDB.calc_family == family) & (dfCMDB.AWS_OS == os) & (dfCMDB.RDS == False) & (dfCMDB.AWS_Region == region)]

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
# Map source DB to AWS_DB

dfCMDB['AWS_DB'] = "" 
dfCMDB_filterrds = dfCMDB[(dfCMDB.RDS == True)] 

print('Mapping RDS instances...')
   
indexes=dfCMDB_filterrds.index.tolist()
for row in indexes:
    if "Oracle" in dfCMDB.loc[row, 'DB Rel/Ver']:
        dfCMDB.loc[row, 'AWS_DB'] = "Oracle"
    elif "SQL " in dfCMDB.loc[row, 'DB Rel/Ver']:
        dfCMDB.loc[row, 'AWS_DB'] = "SQL Server"
    else:
        dfCMDB.loc[row, 'AWS_DB'] = "Aurora MySQL"
        
# Map RDS instances

import boto3
import json
import re
import pandas

regions = {"us-east-1", "eu-central-1", "ap-northeast-2"}
families = {"m", "c", "r", "t"}
dbs = {"Oracle", "SQL Server", "Aurora MySQL"}

print('Pricing RDS...')

for region in regions:
    print('Region ' + region)
    for db in dbs:
        print('DB ' + db)
        for family in families:
            print('Family ' + family)
            # Lets get specific and only get the license included, no pre-installed software, current generation, etc.
            client = boto3.client('pricing')
            
            if region == "us-east-1":
                location = "US East (N. Virginia)"
            elif region == "eu-central-1":
                location = "EU (Frankfurt)"
            else:
                location = "Asia Pacific (Seoul)"
            
            if family == "c":
                instanceFamily = "General purpose"
            elif family == "r":
                instanceFamily = "Memory optimized"
            else:
                instanceFamily = "General purpose"
                
            if db == "Aurora MySQL":
                licensemodel="No license required"
                instanceFamily = "Memory optimized"
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
            d={'instanceType':[], 'memory':[], 'family':[], 'one_hr_rate':[], 'one_yr_rate':[], 'three_yr_rate':[]}
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
                
                if (db == "SQL Server"):
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
                if db == "SQL Server":  
                    sqlhourly=float(jItem['terms']['Reserved'][sku+"."+oneyearterm]['priceDimensions'][sku+"."+oneyearterm+"."+ondemandratecode]['pricePerUnit']['USD'])
                    oneyr_rate = float(oneyr_rate) + (sqlhourly * 8760)

                threeyr_rate=jItem['terms']['Reserved'][sku+"."+threeyearterm]['priceDimensions'][sku+"."+threeyearterm+"."+threeyearratecode]['pricePerUnit']['USD']
           
                # person = input('Enter your name: ')
        
                # Load rates
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
            
            #Convert memory to numeric
            
            dfInstanceList['memory']=dfInstanceList['memory'].apply(pd.to_numeric)
            dfInstanceList['vcpu']=dfInstanceList['vcpu'].apply(pd.to_numeric)
            dfInstanceList['one_hr_rate']=dfInstanceList['one_hr_rate'].apply(pd.to_numeric)
            dfInstanceList['one_yr_rate']=dfInstanceList['one_yr_rate'].apply(pd.to_numeric)
            dfInstanceList['three_yr_rate']=dfInstanceList['three_yr_rate'].apply(pd.to_numeric)

            dfInstanceList_sorted=dfInstanceList.sort_values(by=['vcpu'], ascending=True)
            dfInstanceList_sorted=dfInstanceList_sorted.reset_index(drop=True)
            
            if region == "ap-northeast-2":
                myregion = "ap-southeast-1"
            else: myregion = region
                    
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
ec2_ebs_unit_cost=.151
rds_ebs_unit_cost=.116

for index in dfCMDB_filter.index.tolist():
    if dfCMDB.loc[index, 'RDS'] == True:
        dfCMDB.loc[index, 'ebs_month_rate'] = dfCMDB.loc[index, 'Used Size (GB)'] * rds_ebs_unit_cost
    else:
        dfCMDB.loc[index, 'ebs_month_rate'] = dfCMDB.loc[index, 'Used Size (GB)'] * ec2_ebs_unit_cost

# Write output file
print("Writing output file...")
dfCMDB.to_csv('bom.csv')