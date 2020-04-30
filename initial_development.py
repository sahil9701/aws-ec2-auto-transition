import boto3
import json
import time
import logging
logging.basicConfig(level=logging.DEBUG)
LOGGER=logging.getLogger(__name__)

with open('instancetypes.json') as f:
    instance_database=json.load(f)
ec2=boto3.resource('ec2')
client=boto3.client('ec2')


def ec2_algorithm(instance_type,instance_database,lower_range,higher_range):
    final_filter=[]
    min_price=None
    final_index=None
    for key,value in instance_database["Instance family"].items():
        if value[0]==instance_type[0]:
            if lower_range < int(instance_database["Memory (MiB)"][f'{key}']) < higher_range:
                final_filter.append(key)

    for index in final_filter:
        current_price=float(instance_database["On-Demand Linux pricing"][f'{index}'].split(' USD')[0])
        if not min_price:
            min_price=current_price
            final_index=index
        else:
            if current_price < min_price:
                min_price=current_price
                final_index=index
    return instance_database['Instance type'][final_index]
    #return f"Lowest price is {min_price} and Index is {final_index} Instance Type: {instance_database['Instance type'][final_index]} and RAM: {instance_database['Memory (MiB)'][final_index]}"
def create_AMI(ec2,instance_id,ami_name,description):
    response=ec2.Instance(instance_id).create_image(Name=ami_name,Description=description)
    image_id=response.id
    while ec2.Image(image_id).state !='available':
        time.sleep(15)
    return response
    #have to user waiter bcs it takes lot time to create it

def get_config_instance(ec2,instance_id):
    instance=ec2.Instance(instance_id)
    key_name=instance.key_name
    vpc_id=instance.vpc_id
    security_groups=instance.network_interfaces_attribute[0]['Groups']
    security_group_ids=[i['GroupId'] for i in security_groups]
    #Fetch all the config like security grp, vpc id, key name etc to deploy new instance
    return {
        'key_name':key_name,
        'vpc_id':vpc_id,
        'security_groups':security_group_ids
    }

def deploy_instance(client,ec2,image_id,instance_type,config):
    response=ec2.create_instances(
        ImageId=image_id,
        MinCount=1,
        MaxCount=1,
        InstanceType=instance_type,
        KeyName=config.get('key_name'),
        SecurityGroupIds=config.get('security_groups')
    )
    new_isntance_id=response[0].id
    #while client.describe_instance_status(InstanceIds=list(new_isntance_id))['InstanceStatuses'][0]['InstanceStatus']['Status'] != 'ok':
    #    time.sleep(15)
    return new_isntance_id
    #use waiter for instance to get started

def delete_old_instance(ec2,old_instance_id):
    response=ec2.Instance(old_instance_id).terminate()
    #delete old instance

def delete_image(ec2,image_id):
    #no need for waiters
    response=ec2.Image(image_id).deregister()
    return response

def delete_snapshot(client,ami_id):
    pass
    #TODO skipping for now
    #delete snapshot that has ami_id snapshots
def delete_alarms(alarm_names):
    cloudwatch=boto3.client('cloudwatch')
    response=cloudwatch.delete_alarms(AlarmNames=alarm_names)
    return response

def enable_alarm(alarm_name,threshold,instance_id,arn,comparison_operator):
    cloudwatch=boto3.client('cloudwatch')
    response=cloudwatch.put_metric_alarm(
        AlarmName=alarm_name,
        ComparisonOperator=comparison_operator,
        EvaluationPeriods=1,
        Period=900,
        MetricName='CPUUtilization',
        Namespace='AWS/EC2',
        Statistic='Average',
        Threshold=int(threshold),
        ActionsEnabled=True,
        AlarmDescription=f'Alarm when server CPU exceeds {threshold}%',
        AlarmActions=[arn],
        Dimensions=[
            {
                'Name': 'InstanceId',
                'Value': instance_id
            },
        ]
    )
    return response

    #turn on health check on the new instance
def main(event):

    LOGGER.info('Fetching Instance ID and CPU utilization from lambda trigger')
    current_utilization=json.loads(event['Records'][0]['Sns']['Message'])['NewStateReason']
    current_utilization=int(float(current_utilization[current_utilization.find('[')+1:current_utilization.find('(')-1]))
    old_instance_id=json.loads(event['Records'][0]['Sns']['Message'])['Trigger']['Dimensions'][0]['value']
    #old_instance_id='i-0f3e9df17033ab80e'
    #current_utilization=80
    instance = ec2.Instance(old_instance_id)
    old_instance_type = instance.instance_type
    for key,value in instance_database['Instance type'].items():
        if value==old_instance_type:
            my_index=key
            break
    instance_memory = int(instance_database["Memory (MiB)"][f"{my_index}"])
    if instance_memory==512 and current_utilization < 25:
        return f'No need to scale down the instance.'

    lower_range=(instance_memory*current_utilization)/75
    higher_range=(instance_memory*current_utilization)/25
    if higher_range<512:
        higher_range=514
    LOGGER.debug(f'Instance {old_instance_id} and {old_instance_type} has {current_utilization}% of CPU utilization')
    new_instance_type= ec2_algorithm(old_instance_type, instance_database, lower_range, higher_range)
    LOGGER.debug(f'New Instance type will be {new_instance_type}')

    LOGGER.debug(f'Creating AMI of old instance {old_instance_id} and it will take some time')
    new_ami_id=create_AMI(ec2,old_instance_id,ami_name=f'ami_of_{old_instance_id}',description='vertical scaling').id
    LOGGER.info(f'Successfully created the AMI {new_ami_id}')

    LOGGER.debug(f'Trying to fetch config of old instance {old_instance_id}')
    old_instance_config=get_config_instance(ec2,old_instance_id)
    LOGGER.info(f'Successfully fetched config of old instance')

    LOGGER.debug(f'Trying to create new instance type {new_instance_type} using AMI {new_ami_id}')
    new_instance_id=deploy_instance(client,ec2,new_ami_id,new_instance_type,old_instance_config)
    LOGGER.info(f'Successfully created new instance {new_instance_id}')

    LOGGER.debug(f'Trying to enable cloudwatch Alarm for new instance')
    high_alarm=enable_alarm(alarm_name=f'higher_{new_instance_id}',threshold=75,instance_id=new_instance_id,
                            arn='arn:aws:sns:us-west-1:136960521401:CPU_health_check',
                            comparison_operator='GreaterThanThreshold')

    low_alarm = enable_alarm(alarm_name=f'lower_{new_instance_id}', threshold=25, instance_id=new_instance_id,
                              arn='arn:aws:sns:us-west-1:136960521401:CPU_health_check',
                              comparison_operator='LessThanThreshold')
    LOGGER.info(f'Successfully enabled high and low boundry alarm on new instance')

    LOGGER.debug(f'Now trying to terminate old instance {old_instance_id}')
    delete_instance=delete_old_instance(ec2,old_instance_id)
    LOGGER.debug(f'Successfully deleted old instance')

    LOGGER.debug(f'Now trying to delete old Alarms')
    old_alarms=[f'higher_{old_instance_id}',f'lower_{old_instance_id}']
    deleted_alarms=delete_alarms(old_alarms)
    LOGGER.info(f'Successfully deleted alarms {old_alarms}')

    LOGGER.debug(f'Trying to delete AMI of old instance because we deployed new instance')
    deleted_ami=delete_image(ec2,new_ami_id)
    LOGGER.debug(f'Successfully deleted AMI {new_ami_id}')
