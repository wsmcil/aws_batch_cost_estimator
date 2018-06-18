# AWS Batch cost estimator

This Python script is intended to signficantly reduce the burden of determining an AWS configuration and pricing for large numbers of elements that would be cumbersome to manually input in to the Amazon Web Services Simple Monthly Calculator. This  script will read in a CSV file with details about an existing installation of servers, storage, and databases and determine the equivalent AWS EC2 and RDS configurations as well as then pricing those elements.  The result is written to an output CSV file with the original input CSV elements and the computed fields like EC2 instance type and pricing as appended columns.  Pricing is queried live from the AWS pricing API so the output is always up to date.

The header of the script contains the mappings of expected input fields to the appropriate columns in a given input CSV.  The header also contains the name and location of both the input and the output files.

## Requirements
The scirpt with run on any computer configured with Python.  Remember the input and output file specifications will differ between Windows and Linux based computers.  Once Python is installed, the following Python libraries will also need to be 'pip installed':

1. The AWS CLI tools configured with a key that has IAM privileges for budgets and financials.  Also configure the CLI tools with a default regions which has a pricing API (e.g., us-east-1).  Not all AWS regions have a pricing API hosted, but pricing for all regions is provided by any valid pricing API endpoint.
2. The AWS Boto3 SDK for Python
3. The Pandas Python library
4. The Json Python library
5. The re Python libarary

## Notes
1. Keep in mind the order of magnitude of expected input fields like memory and storage which are expected in GiB.  
2. The script has some fault tolerance if data is left out.  For example, if memory is left out, target EC2 instance types will be calculated based on the nearest provided CPU.  If no region is given, us-east-1 (N. Virginia) is assumed.
3. Storage is assumed to be gp2 with a 1% average daily rate of change for snapshots.
4. EC2 pricing is currently provided three ways:  On-Demand, 1-YR RI All Upfront, and 3-YR RI All Upfront
