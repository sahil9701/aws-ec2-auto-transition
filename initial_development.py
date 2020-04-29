import boto3
import json
with open('instancetypes.json') as f:
    instance_database=json.load(f)

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
    return f"Lowest price is {min_price} and Index is {final_index} Instance Type: {instance_database['Instance type'][final_index]} and RAM: {instance_database['Memory (MiB)'][final_index]}"
def create_AMI(instance_id,ami_name,description):
    #have to user waiter bcs it takes lot time to create it
    pass
def get_config_instance(instance_id):
    #Fetch all the config like security grp, vpc id, key name etc to deploy new instance
    pass
def deploy_instance(image_id,instance_type,keyname):
    pass
    #use waiter for instance to get started
def delete_instance():
    pass
    #delete old instance
def delete_image():
    pass
def delete_snapshot():
    pass
def enable_alarm():
    pass
    #turn on health check on the new instance
def main(event, context):

    current_utilization=json.loads(event['Records'][0]['Sns']['Message'])['NewStateReason']
    current_utilization=int(float(current_utilization[current_utilization.find('[')+1:current_utilization.find('(')-1]))
    instance_id=json.loads(event['Records'][0]['Sns']['Message'])['Trigger']['Dimensions'][0]['value']
    x = boto3.resource('ec2')
    instance = x.Instance(instance_id)
    my_type = instance.instance_type
    for key,value in instance_database['Instance type'].items():
        if value==my_type:
            my_index=key
            break
    instance_memory = int(instance_database["Memory (MiB)"][f"{my_index}"])
    if instance_memory==512 and current_utilization < 25:
        return f'No need to scale down the instance.'

    lower_range=(instance_memory*current_utilization)/75
    higher_range=(instance_memory*current_utilization)/25
    if higher_range<512:
        higher_range=514
    print(ec2_algorithm(my_type, instance_database, lower_range, higher_range))

