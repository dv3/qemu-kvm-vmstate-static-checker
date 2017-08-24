#!/bin/bash -ev
#
#./load_checkers.sh static-checker-up vmstate-static-checker.py virtlab504.virt.lab.eng.bos.redhat.com rhel74 qemu-kvm q35
#
#

echo "testname $1"
echo "testscript $2"
echo "hostname: $3"
echo "host os: $4"
echo "qemu type: $5"
echo "machine type: $6"

testname=$1
testscript=$2
hostname=$3
hostos=$4
qemutype=$5
m_type=$6


#chmod 0600 $WORKSPACE/qemu-jjb/jobs/ssh-key

#ssh -i $WORKSPACE/qemu-jjb/jobs/ssh-key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o GlobalKnownHostsFile=/dev/null root@$EXISTING_NODES "avocado vt-bootstrap --yes-to-all"

#scp -i $WORKSPACE/qemu-jjb/jobs/ssh-key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o GlobalKnownHostsFile=/dev/null $WORKSPACE/qemu-jjb/tests/acceptance_jenkins.txt root@$EXISTING_NODES:/root/

scp -i ~/.ssh/id_rsa.pub ./${testname}.tar.gz  root@${hostname}:/root/${testname}.tar.gz
ssh -i ~/.ssh/id_rsa.pub root@${hostname} "yum -y install tar"
ssh -i ~/.ssh/id_rsa.pub root@${hostname} "tar -xvzf /root/${testname}.tar.gz"

returncode=5
returncode=$(ssh -i ~/.ssh/id_rsa.pub root@${hostname} "/root/${testname}/run_checkers.py --t ${testscript} --v ${hostos} --q ${qemutype} --m ${m_type}" )

echo $returncode
