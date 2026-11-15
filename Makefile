# Lab lifecycle on AWS (details: deploy/lab.sh). Set AWS_PROFILE first.
.PHONY: bootstrap up down status chat token weights redeploy extend leftovers lint-deploy

bootstrap: ; deploy/lab.sh bootstrap
up: ; deploy/lab.sh up
down: ; deploy/lab.sh down
status: ; deploy/lab.sh status
chat: ; deploy/lab.sh chat
token: ; deploy/lab.sh token
weights: ; deploy/lab.sh weights
redeploy: ; deploy/lab.sh redeploy
extend: ; deploy/lab.sh extend $(HOURS)
leftovers: ; deploy/lab.sh leftovers

# Offline checks for the deploy code (no AWS calls).
lint-deploy:
	terraform fmt -check -recursive deploy/terraform
	terraform -chdir=deploy/terraform/bootstrap validate
	terraform -chdir=deploy/terraform/cluster validate
	helm lint deploy/helm/platform --set clusterName=x,nodeRole=y
	helm lint deploy/helm/agent --set api.image.repository=x
	bash -n deploy/lab.sh
