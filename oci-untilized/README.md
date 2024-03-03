# oci-unutilized-resources

[![pipeline status](https://gitlab.****.com/cloudplatform/
oci-unutilized/badges/main/pipeline.svg)](https://gitlab.****.com/cloudplatform/
oci-unutilized/commits/main)
[![coverage report](https://gitlab.****.com/cloudplatform/
oci-unutilized/badges/main/coverage.svg)](https://gitlab.****.com/cloudplatform/
oci-unutilized/-/commits/main)

Prometheus metrics exporter to report oracle cloud infrastruture for unattached block volumes, Network Load Balancers and Load Balancers.

## Supported Clouds

- [x] OCI
- [ ] AWS.

## Supported Kubernetes

Any distributions + v1.19.

Add config file in src dir.

## Prerequisits

1. Kubernetes: a service account with read/update access to the cluster is required, scoped to `PV` resources.<br>
2. Cloud: Respective access is required for block volumes service (BV) with read and delete roles.<br>

3. Refer to the [argo helm chart](https://gitlab.****.com/data/infrastructure/argo-charts/-/tree/master/infra-oci-unutilized-resources) for the deployment setup which address both prerequisits 1 & 2.


## Dry Run

```bash
$ python metrics_exporter.py
```

## Usage

To scan and generate a report:

```bash
python metrics_exporter.py

## Contributing

## License

[MIT License](https://opensource.org/licenses/MIT).
