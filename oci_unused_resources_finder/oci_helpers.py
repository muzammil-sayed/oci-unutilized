# oci_helpers.py

import oci
debug = False

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
