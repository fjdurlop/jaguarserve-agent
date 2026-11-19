"""Tear down lab EKS clusters past their `lab-expires-at` tag (ISO 8601, UTC). Runs every 30 min.

Each run makes progress and is safe to repeat: delete node groups (stops the system node and the
Karpenter controller), terminate instances Karpenter launched for the cluster (GPU nodes), and delete
the cluster once it has no node groups. Only clusters tagged `project=<PROJECT_TAG>` are touched.
"""

import contextlib
import json
import os
from datetime import UTC, datetime

import boto3

PROJECT = os.environ["PROJECT_TAG"]
DRY_RUN = os.environ.get("DRY_RUN", "false") == "true"
eks = boto3.client("eks")
ec2 = boto3.client("ec2")


def _expired(tags: dict, now: datetime) -> bool:
    raw = tags.get("lab-expires-at")
    if tags.get("project") != PROJECT or not raw:
        return False
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")) <= now
    except ValueError:
        return False


def _cluster_instances(cluster: str) -> list[str]:
    ids = []
    pages = ec2.get_paginator("describe_instances").paginate(
        Filters=[
            {"Name": "tag:project", "Values": [PROJECT]},
            {"Name": f"tag:kubernetes.io/cluster/{cluster}", "Values": ["owned"]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]},
        ]
    )
    for page in pages:
        for r in page["Reservations"]:
            ids += [i["InstanceId"] for i in r["Instances"]]
    return ids


def handler(event=None, context=None):
    now = datetime.now(UTC)
    actions = []
    for name in eks.list_clusters()["clusters"]:
        cluster = eks.describe_cluster(name=name)["cluster"]
        if not _expired(cluster.get("tags", {}), now):
            continue
        groups = eks.list_nodegroups(clusterName=name)["nodegroups"]
        for g in groups:
            actions.append(f"delete nodegroup {name}/{g}")
            if not DRY_RUN:
                with contextlib.suppress(eks.exceptions.ResourceInUseException):  # already deleting
                    eks.delete_nodegroup(clusterName=name, nodegroupName=g)
        instances = _cluster_instances(name)
        if instances:
            actions.append(f"terminate {len(instances)} instances of {name}")
            if not DRY_RUN:
                ec2.terminate_instances(InstanceIds=instances)
        if not groups and cluster["status"] not in ("DELETING",):
            actions.append(f"delete cluster {name}")
            if not DRY_RUN:
                eks.delete_cluster(name=name)
    print(json.dumps({"dry_run": DRY_RUN, "actions": actions}))
    return {"actions": actions}
