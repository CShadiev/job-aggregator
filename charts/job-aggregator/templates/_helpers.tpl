{{/*
Common labels applied to every object this chart creates.
*/}}
{{- define "job-aggregator.labels" -}}
app.kubernetes.io/part-of: job-aggregator
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
