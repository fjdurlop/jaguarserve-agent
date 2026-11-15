{{- define "agent.dbEnv" -}}
- name: POSTGRES_PASSWORD
  valueFrom: {secretKeyRef: {name: {{ .Values.secretName }}, key: POSTGRES_PASSWORD}}
- name: STORE
  value: pg
- name: DATABASE_URL
  value: postgresql://agent:$(POSTGRES_PASSWORD)@postgres:5432/agent
- name: EMBEDDING_MODEL
  value: {{ .Values.api.env.EMBEDDING_MODEL | quote }}
- name: FASTEMBED_CACHE_PATH
  value: /cache/fastembed
- name: HF_HOME
  value: /cache/hf
{{- end }}

{{- define "agent.waitForDb" -}}
- name: wait-for-postgres
  image: {{ .Values.postgres.image }}
  command: ["sh", "-c", "until pg_isready -h postgres -U agent -d agent; do sleep 2; done"]
  securityContext: {allowPrivilegeEscalation: false}
{{- end }}

{{- define "agent.podSecurity" -}}
securityContext: {runAsNonRoot: true, runAsUser: 10001, seccompProfile: {type: RuntimeDefault}}
{{- end }}
