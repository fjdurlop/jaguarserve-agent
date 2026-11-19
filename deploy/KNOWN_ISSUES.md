# EKS lab: known issues

Problems found in the first real lab session (`deploy/lab.sh up` → chat → `down`, eu-north-1, 2026-11-18).
Each entry gives the symptom, the cause, the workaround used, and the fix status.

| # | Issue | Status |
|---|---|---|
| 1 | vLLM crash loop: `VLLM_PORT` injected by Kubernetes | fixed in chart |
| 2 | `lab.sh down` hangs: Karpenter loses AWS access before its finalizer runs | fixed in `lab.sh` (not yet tested on a cluster) |
| 3 | vLLM rollout deadlock with a single GPU | fixed: `Recreate` in lab, rolling update by default |
| 4 | Default GPU instance list too narrow for real capacity | fixed: wider default |
| 5 | Expired `public.ecr.aws` Helm login blocks chart pulls | workaround |
| 6 | No GPU capacity in the region for ~20 min | risk, no fix in code |

---

## 1. vLLM crash loop: `VLLM_PORT` injected by Kubernetes

**Symptom.** The vLLM pod restarts in a loop right after start; the log shows vLLM rejecting `VLLM_PORT`.

**Cause.** The chart has a Service named `vllm`. With service links enabled (the Kubernetes default),
every pod in the namespace gets Docker-link variables for it, among them `VLLM_PORT=tcp://<ip>:8000`.
vLLM reads every `VLLM_*` variable as its own configuration and refuses a port that is not an integer.

**Fix.** `enableServiceLinks: false` on the vLLM pod (`deploy/helm/agent/templates/vllm.yaml`).
Nothing in the pod uses the link variables; the API reaches vLLM through cluster DNS.

## 2. `lab.sh down` hangs: Karpenter loses AWS access before its finalizer runs

**Symptom.** `terraform destroy` stalls on `helm_release.platform` until the Helm timeout, then the
internet gateway cannot be deleted ("has mapped public addresses").

**Cause.** `lab.sh down` deletes the NodePools and waits for NodeClaims, but leaves the EC2NodeClass to
Terraform. Terraform destroys in dependency order as it sees it and removes the public route table
early. Karpenter runs in a subnet without a NAT, so from that moment it cannot call the AWS APIs. The
EC2NodeClass finalizer (which deletes Karpenter's instance profile) never completes, so the Helm release
cannot uninstall, and anything still holding a public IP keeps the internet gateway in place.

**Workaround used.**
1. `kubectl patch ec2nodeclass <name> --type=merge -p '{"metadata":{"finalizers":null}}'`
2. Run `deploy/lab.sh down` again.
3. Delete the Karpenter instance profile by hand (`aws iam list-instance-profiles`, then
   `remove-role-from-instance-profile` and `delete-instance-profile`) and the EKS log group if it remains.

**Fix.** `cmd_down` now deletes the EC2NodeClass and waits for it
(`kubectl delete ec2nodeclasses --all --wait`) right after the NodeClaims are gone, while the network is
still intact, before `terraform destroy`. Not yet run against a real cluster; if it still hangs, the
fallback is to destroy the `helm_release.*` resources first with `-target`, then the rest.

## 3. vLLM rollout deadlock with a single GPU

**Symptom.** After a chart change, the vLLM Deployment never finishes rolling out: the new pod stays
Pending and the old (broken) pod stays.

**Cause.** The strategy is `RollingUpdate` with `maxSurge: 1, maxUnavailable: 0`, so the new pod must be
Ready before the old one goes. That needs a second GPU node at the same time. With a GPU quota or market
that gives only one node, the new pod never schedules, and the rollout waits forever. It is worst when
the old pod is already broken (issue 1): nothing serves and nothing progresses.

**Workaround used.** Live patch to `maxSurge: 0, maxUnavailable: 1` (old pod goes first, short outage).

**Fix.** Chart value `vllm.rolloutStrategy`: `RollingUpdate` by default (no downtime, for a setup that
can get a second GPU), `Recreate` set by `lab.sh` (old pod goes first; chat is down for the vLLM start,
about 2–3 min with a cached image).

## 4. Default GPU instance list too narrow for real capacity

**Symptom.** With the defaults, Karpenter could not get any GPU node: spot and on-demand both failed.

**Cause.** The default list is `["g6.xlarge", "g5.xlarge"]` (`deploy/terraform/cluster/variables.tf`,
`deploy/helm/platform/values.yaml`). In the session neither had capacity. The node finally came from a
wider list passed with `-var` (`g6.xlarge, g5.xlarge, g6.2xlarge, g6.4xlarge, g6e.xlarge`): a
`g6.4xlarge` on-demand.

**Fix.** The wider list is now the default in both places; Karpenter picks the cheapest available
type. Keep the quota in mind: the spot G-instance quota
(8 vCPU) does not fit a `g6.4xlarge` (16 vCPU), so that type can only come on demand.

## 5. Expired `public.ecr.aws` Helm login blocks chart pulls

**Symptom.** `helm install` / Terraform `helm_release` fails pulling charts from `oci://public.ecr.aws/...`
(Karpenter) with an authentication error, although the registry is public.

**Cause.** A stale credential for `public.ecr.aws` in the Helm registry config is sent and rejected.

**Workaround.** `helm registry logout public.ecr.aws`, then retry. Anonymous pulls work.

## 6. No GPU capacity in the region for ~20 min

**Symptom.** After KEDA woke vLLM (0 → 1), Karpenter could not launch any GPU instance for about 20
minutes (spot placement score 1/10). The API streamed `warming_up`, then `llm_unavailable` with the
handoff text, which is the intended graceful path.

**Cause.** Market capacity, not configuration. G-instance quota exists in only one region for this
account, so there is nowhere else to go.

**Mitigation.** A wider instance list (issue 4) helps. A second region with GPU quota would remove the
single point of failure; there is no code change for that yet.
