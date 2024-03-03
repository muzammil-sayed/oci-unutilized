import oci

# Initialize the OCI client with the appropriate config
oci_config = oci.config.from_file("~/.oci/config")
identity = oci.identity.IdentityClient(oci_config)
block_storage = oci.core.BlockstorageClient(oci_config)

def get_compartments(compartment_id):
    # Get all compartments in the tenancy
    compartments = identity.list_compartments(compartment_id).data

    # Traverse the subcompartments
    for compartment in compartments:
        # print(f"Compartment: {compartment.name}, ID: {compartment.id}")
        get_compartments(compartment.id)

# Start the traversal at the root compartment (tenancy)
get_compartments(oci_config["tenancy"])

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



def traverse_compartments(compartment_id):
    # Get the unattached volumes in the current compartment
    unattached_volumes = get_unattached_volumes(compartment_id)

    # Get the subcompartments
    subcompartments = identity.list_compartments(compartment_id).data

    # Traverse the subcompartments
    for subcompartment in subcompartments:
        unattached_volumes += traverse_compartments(subcompartment.id)

    return unattached_volumes

# Start the traversal at the root compartment
unattached_volumes = traverse_compartments(oci_config["tenancy"])

# Print the Prometheus metrics
for volume in unattached_volumes:
    print(f'oci_volume_available{{id="{volume.id}", compartment="{volume.compartment_id}"}} 1')


def generate_prometheus_metrics(compartment_id):
    # Traverse compartments and get unattached volumes
    unattached_volumes = traverse_compartments(compartment_id)

    # Generate Prometheus metrics
    for volume in unattached_volumes:
        print(f'oci_volume_available{{id="{volume.id}", compartment="{volume.compartment_id}"}} 1')

# Start the traversal at the root compartment (tenancy)
generate_prometheus_metrics(oci_config["tenancy"])