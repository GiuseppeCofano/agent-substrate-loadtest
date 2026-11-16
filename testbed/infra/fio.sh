#!/usr/bin/env bash
# Measures the disk behind /var/lib/ate on one agents-substrate node with fio
# and writes fio's JSON to <out>/fio.json.
# Jobs: sequential 1 MiB writes (one stream, like one checkpoint, and four
# streams, like overlapping checkpoints), sequential 1 MiB reads (a restore),
# and 4 KiB random writes and reads at queue depth 1 (latency).
set -o errexit -o nounset -o pipefail

out="${1:?usage: $0 <out-dir>}"
mkdir -p "${out}"
node="$(kubectl get nodes -l cloud.google.com/gke-nodepool=agents-substrate -o jsonpath='{.items[0].metadata.name}')"
kubectl -n kube-system delete pod fio --ignore-not-found --wait=true >/dev/null
kubectl apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata: {name: fio, namespace: kube-system}
spec:
  nodeName: ${node}
  restartPolicy: Never
  tolerations: [{operator: Exists}]
  containers:
  - name: fio
    image: debian:12-slim
    securityContext: {privileged: true}
    volumeMounts: [{name: ate, mountPath: /data}]
    command:
    - /bin/sh
    - -c
    - |
      set -e
      apt-get update -qq >/dev/null && apt-get install -y -qq fio >/dev/null
      mkdir -p /data/fio && cd /data/fio
      common="--direct=1 --ioengine=libaio --group_reporting --output-format=json"
      echo "== seqwrite1";   fio \$common --name=seqwrite1 --rw=write --bs=1M --iodepth=16 --numjobs=1 --size=16G --time_based --runtime=60 --filename=f1
      echo "== seqwrite4";   fio \$common --name=seqwrite4 --rw=write --bs=1M --iodepth=16 --numjobs=4 --size=4G --time_based --runtime=60
      echo "== seqread1";    fio \$common --name=seqread1 --rw=read --bs=1M --iodepth=16 --numjobs=1 --size=16G --time_based --runtime=60 --filename=f1
      echo "== randwrite4k"; fio \$common --name=randwrite4k --rw=randwrite --bs=4k --iodepth=1 --numjobs=1 --size=4G --time_based --runtime=30 --filename=f1
      echo "== randread4k";  fio \$common --name=randread4k --rw=randread --bs=4k --iodepth=1 --numjobs=1 --size=4G --time_based --runtime=30 --filename=f1
      rm -rf /data/fio
      echo "== done"
  volumes: [{name: ate, hostPath: {path: /var/lib/ate, type: Directory}}]
YAML
kubectl -n kube-system wait --for=jsonpath='{.status.phase}'=Succeeded pod/fio --timeout=900s >/dev/null
kubectl -n kube-system logs fio > "${out}/fio.log"
kubectl -n kube-system delete pod fio --wait=false >/dev/null
echo "fio results in ${out}/fio.log (node ${node})"
