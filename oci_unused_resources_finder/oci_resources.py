# List resources in an OCI tenancy
#
# Parameters:
# 		profile_name
# 		(credentials are then picked up from the config file)
#       -c <compartment_id> - only show resources within this compartment and any subcompartments

from flask import Flask, render_template, request, jsonify
import argparse
import csv
import re
import sys
import time
from string import Formatter
import oci
# from oci_helpers import get_compartment_list, traverse, debug
from flask import render_template_string 
from oci_helpers import get_compartment_list, traverse, debug
# import argparse
# import csv
# import re
# import sys
# import time
# from string import Formatter

import oci

# Enable debug logging
# import logging
# logging.basicConfig()
# logging.getLogger('oci').setLevel(logging.DEBUG)
app = Flask(__name__, template_folder='templates')

################################################################################################
debug = False
output_dir = "./log"
################################################################################################

# Output formats for readable, columns style output and csv files
field_names = ['Tenancy', 'Region', 'Compartment', 'Type', 'Name', 'State', 'DB',
				'Shape', 'OCPU', 'GBytes', 'BYOLstatus',	'VolAttached', 'Created', 'CreatedBy', 'OCID']
print_format = '{Tenancy:24s} {Region:14s} {Compartment:54s} {Type:26s} {Name:54.54s} {State:18s} {DB:4s} ' \
				'{Shape:20s} {OCPU:4d} {GBytes:>8.3f} {BYOLstatus:10s} {VolAttached:12s} {Created:32s} {CreatedBy:32s} {OCID:120}'

# Header format removes the named placeholders
header_format = re.sub('{[A-Z,a-z]*', '{', print_format)  # Remove names
header_format = re.sub('\.[0-9]*', '', header_format)     # Remove decimal
header_format = re.sub('f}', 's}', header_format)     # replace float w. string
header_format = re.sub('d}', 's}', header_format)     # replace decimal w. string

# Fixed strings
BYOL = "BYOL"
NONBYOL = "*NON-BYOL*"
profile_name = "DEFAULT"

def debug_out(out_str):
	if debug:
		print(out_str)


# Get compartment full name (path) from the compartment list dictionary
def get_compartment_name(compartment_id, compartment_list):
	for comp in compartment_list:
		if comp['id'] == compartment_id:
			return comp['path']
	return 'Not Found'


def list_tenancy_resources(compartment_list, base_compartment_id):
	global tenancy_name
	global regions
	global config
	result_data = []

	# Headings
	vformat = Formatter().vformat
	print(vformat(header_format, field_names, ''))

	# CSV output
	# csv_writer = csv_open(f"oci-{profile_name}")

	# Search all resources
	# for region in (r for r in regions if r.region_name == 'eu-frankfurt-1'):
	for region in regions:

		config['region'] = region.region_name
		resource_search_client = oci.resource_search.ResourceSearchClient(config)
		db_client = oci.database.DatabaseClient(config)
		compute_client = oci.core.ComputeClient(config)
		analytics_client = oci.analytics.AnalyticsClient(config)
		integration_client = oci.integration.IntegrationInstanceClient(config)
		block_storage_client = oci.core.BlockstorageClient(config)
		object_store_client = oci.object_storage.ObjectStorageClient(config)
		file_storage_client = oci.file_storage.FileStorageClient(config)
		redis_client = oci.redis.RedisClusterClient(config)
		load_balancer_client = oci.load_balancer.LoadBalancerClient(config)
		
		attached_volumes = []

		# When the base compartment is not the tenancy root, filter on list of
		# supplied compartment_ids from compartment_list
		# This builds up the where clause for the query string
		compartment_filter = ''
		if base_compartment_id is not None:
			first = True
			for c in compartment_list:
				if not first:
					compartment_filter += ' || '
				else:
					first = False
				compartment_filter += f" compartmentId = '{c['id']}'"

		try:

			# Get a list of all instances and the volumes attached to them so we can later spot volumes that are unattached
			instance_search_spec = oci.resource_search.models.StructuredSearchDetails()
			query_string = 'query Instance resources'
			if compartment_filter != '':
				query_string += ' where ' + compartment_filter

			instance_search_spec.query = query_string
			instances = resource_search_client.search_resources(search_details=instance_search_spec).data

			for instance in instances.items:
				compartment_id = instance.compartment_id
				instance_id = instance.identifier
				availability_domain = instance.availability_domain

				# Find all volumes attached to instances
				volume_attachments = oci.pagination.list_call_get_all_results(
					compute_client.list_volume_attachments,
					compartment_id=compartment_id,
					instance_id=instance_id
				).data

				# Find all boot volumes attached
				boot_volume_attachments = oci.pagination.list_call_get_all_results(
					compute_client.list_boot_volume_attachments,
					compartment_id=compartment_id,
					instance_id=instance_id,
					availability_domain=availability_domain
				).data

				# looping through all the volumes/bootVol attached and add it to the list
				for volume in volume_attachments:
					attached_volumes.append(volume.volume_id)

				for bootVolume in boot_volume_attachments:
					attached_volumes.append(bootVolume.boot_volume_id)

			# TODO: ADD:
			# ApiGateway 1M msgs/month
			# OKE
			# DataSafePrivateEndpoint (endpoints per month)
			# bastion

			resource_types = [
				'autonomousdatabase', 'autonomouscontainerdatabase', 'analyticsinstance',
				'bootvolume', 'bootvolumebackup', 'bucket', 'database', 'dbsystem',
				'datasafeprivateendpoint', 'loadbalancer', 'volumegroup',
				'apigateway', 'apideployment',
				'datasciencemodel', 'datasciencenotebooksession', 'datascienceproject',
				'filesystem', 'functionsapplication', 'functionsfunction',
				'image', 'instance', 'integrationinstance',
				'mounttarget', 'oceinstance',
				'odainstance', 'vault', 'vaultsecret', 'volume', 'volumegroup', 'volumebackup', 'volumegroupbackup'
			]
			# resource_types = ['all']

			# Some regions don't have all resource types, and query fails, so excelude certain types
			try:
				if region.region_name == 'us-sanjose-1':
					resource_types.remove('oceinstance')
					# resource_types.remove('datasciencemodel')
					# resource_types.remove('datasciencenotebooksession')
					# resource_types.remove('datascienceproject')
				elif region.region_name == 'eu-milan-1':
					resource_types.remove('oceinstance')
				elif region.region_name == 'eu-stockholm-1':
					resource_types.remove('oceinstance')
			except ValueError:
				pass  # ignore value errors

			resource_type_list = ', '.join(resource_types)   # To comma sep string

			# Not interested in terminated resources
			query_filter = "where lifecycleState != 'DELETED' "
			query_filter += "&& lifecycleState != 'TERMINATED' "
			query_filter += "&& lifecycleState != 'Terminated' "
			if compartment_filter != "":
				query_filter += " && (" + compartment_filter + ") "
			query_filter += "sorted by compartmentId asc"

			search_spec = oci.resource_search.models.StructuredSearchDetails()
			search_spec.query = f"query {resource_type_list} resources {query_filter}"

			resources = oci.pagination.list_call_get_all_results(
				resource_search_client.search_resources,
				search_details=search_spec
			).data

			# Skip compartments as a resource type (OCI where clause doesn't seem to support this filter)
			exclude_types = ['Compartment', 'User']
			resource_generator = (r for r in resources if r.resource_type not in exclude_types)
			for resource in resource_generator:

				debug_out(f'ID: {resource.identifier}, Type: {resource.resource_type}')

				# Some items do not have a display name (eg. Tag Namespace)
				resource_name = '-' if resource.display_name is None else resource.display_name

				db_workload = ''
				shape = ''
				cpu_core_count = 0
				storage_gbs = 0.0
				byol_flag = ''
				volume_attachment_flag = ''

				# Dynamic tag used to identify creator, missing on some resources
				created_by = ''
				try:
					# Only interested in tracking down the creator (person), so strip off the
					# oracleidentitycloudservice/ before the username
					created_by = resource.defined_tags['Owner']['Creator'].replace('oracleidentitycloudservice/', '')
				except:
					# Ignore all errors such as tag missing
					pass

				# Some items do not return a lifecycle state (eg. Tags)
				state = '-' if resource.lifecycle_state is None else resource.lifecycle_state

				compartment_name = get_compartment_name(resource.compartment_id, compartment_list)

				if resource.resource_type == 'Instance':
					resource_detail = compute_client.get_instance(resource.identifier).data
					shape = resource_detail.shape
					cpu_core_count = int(resource_detail.shape_config.ocpus)

				if resource.resource_type == 'Bucket':
					namespace = object_store_client.get_namespace().data
					fields = ['approximateCount', 'approximateSize']
					resource_detail = object_store_client.get_bucket(namespace, resource.display_name, fields=fields).data
					storage_gbs = resource_detail.approximate_size / 1e9   # Bytes to Gigabytes

				if resource.resource_type == 'FileSystem':
					resource_detail = file_storage_client.get_file_system(resource.identifier).data
					storage_gbs = resource_detail.metered_bytes / 1e9      # Bytes to Gigabytes

				elif resource.resource_type == 'AutonomousDatabase':
					resource_detail = db_client.get_autonomous_database(resource.identifier).data
					db_workload = resource_detail.db_workload
					cpu_core_count = resource_detail.cpu_core_count
					storage_gbs = resource_detail.data_storage_size_in_tbs * 1024.0
					byol_flag = BYOL if resource_detail.license_model == "BRING_YOUR_OWN_LICENSE" else NONBYOL

				elif resource.resource_type == 'Database':
					resource_detail = db_client.get_database(resource.identifier).data
					resource_name = resource_detail.db_name

				elif resource.resource_type == 'loadbalancer':
					resource_detail = load_balancer_client.list_load_balancers(resource.identifier).data
					resource_name = resource_detail.displayName

				elif resource.resource_type == 'DbSystem':
					resource_detail = db_client.get_db_system(resource.identifier).data
					shape = resource_detail.shape
					storage_gbs = float(resource_detail.data_storage_size_in_gbs)
					cpu_core_count = resource_detail.cpu_core_count
					node_count = resource_detail.node_count

					# Get status of DB Node instead of the dbsystem
					# This more accurately reflects the status of the DB Server
					node_list = db_client.list_db_nodes(resource.compartment_id, db_system_id=resource.identifier)

					state = 'STOPPED (NODE)'
					for node in node_list.data:
						if node.lifecycle_state == 'AVAILABLE':
							state = 'AVAILABLE(NODE)'

					if node_count is not None and node_count > 1:
						shape = shape + '(x' + str(node_count) + ')'

					byol_flag = BYOL if resource_detail.license_model == "BRING_YOUR_OWN_LICENSE" else NONBYOL

				elif resource.resource_type == 'Volume':
					resource_detail = block_storage_client.get_volume(resource.identifier).data
					storage_gbs = float(resource_detail.size_in_gbs)

				elif resource.resource_type == 'BootVolume':
					resource_detail = block_storage_client.get_boot_volume(resource.identifier).data
					storage_gbs = float(resource_detail.size_in_gbs)

				elif resource.resource_type == 'BootVolumeBackup':
					resource_detail = block_storage_client.get_boot_volume_backup(resource.identifier).data
					storage_gbs = float(resource_detail.size_in_gbs)

				elif resource.resource_type == 'AnalyticsInstance':
					resource_detail = analytics_client.get_analytics_instance(resource.identifier).data
					if resource_detail.capacity.capacity_type == 'OLPU_COUNT':
						cpu_core_count = int(resource_detail.capacity.capacity_value)
					byol_flag = BYOL if resource_detail.license_type == "BRING_YOUR_OWN_LICENSE" else NONBYOL

				elif resource.resource_type == 'IntegrationInstance':
					resource_detail = integration_client.get_integration_instance(resource.identifier).data
					byol_flag = BYOL if resource_detail.is_byol else NONBYOL

				# Check if volumes are in use
				if resource.resource_type == 'Volume' or resource.resource_type == 'BootVolume':
					volume_attachment_flag = "Attached" if resource.identifier in attached_volumes else "Not Attached"

				output_dict = {
					'Tenancy': tenancy_name,
					'Region': region.region_name,
					'Compartment': compartment_name,
					'Type': resource.resource_type,
					'Name': resource_name,
					'State': state,
					'DB': db_workload,
					'Shape': shape,
					'OCPU': cpu_core_count,
					'GBytes': storage_gbs,
					'BYOLstatus': byol_flag,
					'VolAttached': volume_attachment_flag,
					'Created': resource.time_created.strftime("%Y-%m-%d %H:%M:%S"),
					'CreatedBy': created_by,
					'OCID': resource.identifier
				}

				#format_output(output_dict, compartment_name, region.region_name)
				result_data.append(output_dict)
			return result_data

		except oci.exceptions.ServiceError as e:
			print(f"Error: {e.code}, {e.message}  (region={region.region_name})", file=sys.stderr)

		except Exception as error:
			print(f'Error: {error}', file=sys.stderr)

	return


# Traverse the compartment list to build the full compartment path
def traverse(compartments, parent_id, parent_path, compartment_list):
	next_level_compartments = [c for c in compartments if c.compartment_id == parent_id]

	for compartment in next_level_compartments:
		# Skip the CASB compartment as it's only a proxy and throws an error
		# CASB compartment does not show up in the OCI console
		# Only look at ACTIVE compartments (deleted ones are still returned and throw permission errors)
		if compartment.name[0:17] != 'casb_compartment.' and compartment.lifecycle_state == 'ACTIVE':
			path = parent_path + '/' + compartment.name
			compartment_list.append(
				dict(id=compartment.id, name=compartment.name, path=path, state=compartment.lifecycle_state)
			)
			traverse(compartments, parent_id=compartment.id, parent_path=path, compartment_list=compartment_list)
	return compartment_list


def get_compartment_list(profile, base_compartment_id):
	global tenancy_name
	global regions
	global ADs
	global config

	# Load config data from ~/.oci/config
	config = oci.config.from_file(profile_name=profile)
	tenancy_id = config['tenancy']

	identity = oci.identity.IdentityClient(config)
	tenancy_name = identity.get_tenancy(tenancy_id).data.name

	# Get Regions
	regions = identity.list_region_subscriptions(tenancy_id).data

	if base_compartment_id is None:
		base_compartment_id = tenancy_id

	# Get list of all compartments in tenancy
	compartments = oci.pagination.list_call_get_all_results(
		identity.list_compartments, tenancy_id,
		compartment_id_in_subtree=True).data

	comp = identity.get_compartment(base_compartment_id).data
	base_compartment_name = comp.name
	base_path = '/' + base_compartment_name

	# Got the flat list of compartments, now construct full path of each which makes it much easier to locate resources
	# Start with base compartment in dictionary
	compartment_path_list = [dict(id=base_compartment_id, name=base_compartment_name, path=base_path, state='Root')]

	# Recurse through all compartments starting at the required root to produce a sub-tree
	# with a path field like: /root/comp1/sub-comp1 etc.
	compartment_path_list = traverse(compartments, base_compartment_id, base_path, compartment_path_list)
	compartment_path_list = sorted(compartment_path_list, key=lambda c: c['path'].lower())

	return compartment_path_list


def csv_open(filename):
	csv_path = f'{output_dir}/{filename}.csv'

	csv_file = open(csv_path, 'wt')

	if debug:
		print('CSV File : ' + csv_path)

	csv_writer = csv.DictWriter(
		csv_file,
		lineterminator='\n',
		fieldnames=field_names, delimiter=',',
		dialect='excel',
		quotechar='"', quoting=csv.QUOTE_MINIMAL)

	csv_writer.writeheader()

	return csv_writer


# Output a line for each cloud resource (output_dict should be a dictionary)
def format_output(output_dict, compartment_name, region_name):
    try:
        # Readable format to stdout
        print(print_format.format(**output_dict))

        # Debugging: print the output_dict to the console
        print(f'Debug - Output Dict: {output_dict}')

        # Render the HTML template with the output data
        html_output = render_template_string('''
            <div>
                <p>Tenancy: {{ output_dict['Tenancy'] }}</p>
                <p>Region: {{ region_name }}</p>
                <p>Compartment: {{ compartment_name }}</p>
				<p>Type: {{ resource_type }}</p>
				<p>Name: {{ resource_name }}</p>
				<p>State: {{ state }}</p>
				<p>DB: {{ db_workload }}</p>
				<p>OCPU: {{ cpu_core_count }}</p>
				<p>GBytes: {{ storage_gbs }}</p>
				<p>BYOLstatus: {{ byol_flag }}</p>
				<p>VolAttached: {{ volume_attachment_flag }}</p>
				<p>Created: {{ resource.time_created.strftime("%Y-%m-%d %H:%M:%S") }}</p>
				<p>CreatedBy: {{ created_by }}</p>
				<p>OCID: {{ identifier }}</p>
            </div>
        ''', output_dict=output_dict)

        # Return the HTML representation
        return html_output
    except Exception as error:
        print(f'Error {error} processing [{output_dict}]', file=sys.stderr)


# Globals at tenancy level Regions & Compartments
tenancy_name = ''
config = {}
regions = {}
ADs = {}

@app.route('/')
def index():
    # Fetch the compartment list for the dropdown menu
    compartment_list = get_compartment_list("DEFAULT", None)
    return render_template('index.html', compartment_path_list=compartment_list)

@app.route('/submit', methods=['POST'])
def submit():
    # Set the profile name as "DEFAULT" by default
    profile_name = "DEFAULT"

    try:
        # Get the selected compartment ID from the form
        compartment_id = request.form['compartment_id']

        # Get list of compartments
        compartment_list = get_compartment_list(profile_name, compartment_id)

        # Get the name of the selected compartment
        compartment_name = get_compartment_name(compartment_id, compartment_list)

        # Call the function to list resources
        result_data = list_tenancy_resources(compartment_list, compartment_id)

        # Render the results on a new page (result.html)
        return render_template('result.html', result=result_data)
    except Exception as e:
        print(f"Error in submit function: {e}")
        return f"<h1>Error in form submission. Please check the console for details.</h1>"

if __name__ == '__main__':
    # Run the Flask app
    app.run(debug=True)
