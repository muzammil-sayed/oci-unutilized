from flask import Flask, render_template, request, jsonify
import argparse
import csv
import re
import sys
import time
from string import Formatter
import oci
from oci_helpers import get_compartment_list, traverse, debug
from flask import render_template_string 

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

				format_output(output_dict)

		except oci.exceptions.ServiceError as e:
			print(f"Error: {e.code}, {e.message}  (region={region.region_name})", file=sys.stderr)

		except Exception as error:
			print(f'Error: {error}', file=sys.stderr)

	return

# Globals at tenancy level Regions & Compartments
tenancy_name = ''
config = {}
regions = {}
ADs = {}

# Output a line for each cloud resource (output_dict should be a dictionary)
def format_output(output_dict):
    try:
        # Readable format to stdout
        print(print_format.format(**output_dict))

        # Debugging: print the output_dict to the console
        print(f'Debug - Output Dict: {output_dict}')

        # Render the HTML template with the output data
        html_output = render_template_string('''
            <div>
                <p>Tenancy: {{ output_dict['Tenancy'] }}</p>
                <p>Region: {{ output_dict['Region'] }}</p>
                <p>Compartment: {{ output_dict['Compartment'] }}</p>
                <!-- Add more lines for other fields -->
            </div>
        ''', output_dict=output_dict)

        # Return the HTML representation
        return html_output
    except Exception as error:
        print(f'Error {error} processing [{output_dict}]', file=sys.stderr)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    try:
        profile_name = request.form['profile_name']
        compartment_id = request.form['compartment_id']

        print(f'Profile Name: {profile_name}, Compartment ID: {compartment_id}')

        # Get list of compartments
        compartment_list = get_compartment_list(profile_name, compartment_id)

        # List all the resources in each compartment
        resources = list_tenancy_resources(profile_name, compartment_id)

        if not resources:
            return jsonify({'error': 'No results returned from list_tenancy_resources function.'})

        # Format the output for each resource
        formatted_outputs = [format_output(resource) for resource in resources]

        # Return the formatted HTML representations
        return jsonify({'html_outputs': formatted_outputs})
    except Exception as e:
        print(f"Error in submit function: {e}")
        # Return an error in JSON format
        return jsonify({'error': 'Error in form submission. Please check the console for details.'})

if __name__ == '__main__':
    # Run the Flask app
    app.run(debug=True)
