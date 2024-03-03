from flask import Flask, Response
import oci

# Initialize the OCI client with the appropriate config
oci_config = oci.config.from_file("config")
identity = oci.identity.IdentityClient(oci_config)
block_storage = oci.core.BlockstorageClient(oci_config)
load_balancer_client = oci.load_balancer.LoadBalancerClient(oci_config)
network_load_balancer_client = oci.network_load_balancer.NetworkLoadBalancerClient(oci_config)

app = Flask(__name__)

def get_unattached_volumes(compartment_id):
    # Get all volumes in the compartment
    volumes = block_storage.list_volumes(compartment_id=compartment_id).data

    # Get all instances in the compartment
    compute = oci.core.ComputeClient(oci_config)
    instances = compute.list_instances(compartment_id=compartment_id).data

    # Get the IDs of all attached volumes
    attached_volume_ids = []
    for instance in instances:
        volume_attachments = compute.list_volume_attachments(compartment_id=compartment_id, instance_id=instance.id).data
        attached_volume_ids += [va.volume_id for va in volume_attachments]

    # Filter out the volumes that are attached
    unattached_volumes = [v for v in volumes if v.id not in attached_volume_ids]

    return unattached_volumes

def get_load_balancers_without_backends(compartment_id):
    # Get all load balancers in the compartment
    load_balancers = load_balancer_client.list_load_balancers(compartment_id).data

    # Filter out the ones that have backend sets
    load_balancers_without_backends = []
    for lb in load_balancers:
        backend_sets = load_balancer_client.list_backend_sets(lb.id).data
        if not backend_sets:
            load_balancers_without_backends.append(lb)

    return load_balancers_without_backends

def get_network_load_balancers_without_backends(compartment_id):
    # Get all network load balancers in the compartment
    network_load_balancers = network_load_balancer_client.list_network_load_balancers(compartment_id).data.items

    # Filter out the ones that have backend sets
    network_load_balancers_without_backends = []
    for nlb in network_load_balancers:
        backend_sets = network_load_balancer_client.list_backend_sets(nlb.id).data.items
        if not backend_sets:
            network_load_balancers_without_backends.append(nlb)

    return network_load_balancers_without_backends


def traverse_compartments(compartment_id):
    # Get the unattached volumes, load balancers and network load balancers without backends in the current compartment
    unattached_volumes = get_unattached_volumes(compartment_id)
    load_balancers_without_backends = get_load_balancers_without_backends(compartment_id)
    network_load_balancers_without_backends = get_network_load_balancers_without_backends(compartment_id)

    # Get the subcompartments
    subcompartments = identity.list_compartments(compartment_id).data

    # Traverse the subcompartments
    for subcompartment in subcompartments:
        volumes, lb_without_backends, nlb_without_backends = traverse_compartments(subcompartment.id)
        unattached_volumes += volumes
        load_balancers_without_backends += lb_without_backends
        network_load_balancers_without_backends += nlb_without_backends

    return unattached_volumes, load_balancers_without_backends, network_load_balancers_without_backends

@app.route('/metrics')
def metrics():
    # Traverse compartments and get unattached volumes, load balancers and network load balancers without backends
    unattached_volumes, load_balancers_without_backends, network_load_balancers_without_backends = traverse_compartments(oci_config["tenancy"])

    # Generate Prometheus metrics
    metrics = []
    for volume in unattached_volumes:
        compartment = identity.get_compartment(volume.compartment_id).data
        metrics.append(f'oci_volume_unattached{{id="{volume.id}", compartment="{compartment.name}"}} 1')
    for lb in load_balancers_without_backends:
        metrics.append(f'oci_load_balancer_without_backends{{id="{lb.id}", name="{lb.display_name}"}} 1')
    for nlb in network_load_balancers_without_backends:
        metrics.append(f'oci_network_load_balancer_without_backends{{id="{nlb.id}", name="{nlb.display_name}"}} 1')

    return Response('\n'.join(metrics), mimetype='text/plain')

if __name__ == '__main__':
    app.run(host='0.0.0.0')
