#!/bin/sh
''''which python >/dev/null 2>&1 && exec python "$0" "$@" # '''
''''which python3 >/dev/null 2>&1 && exec python3 "$0" "$@" # '''
''''exec echo "Error: I can't find python anywhere"         # '''
#
# ./run_checkers.py --t vmstate-static-checker.py --v rhel74 --q qemu-kvm-rhev --m rhel6.5.0
#
# ./run_checker.py --t vmstate-static-checker.py --v f27 --q qemu-kvm --m pc-i440fx-2.5
#
#
# This script is intended to work in python 2.7+ and python 3.3+
# It's a driver for other tests such as compat, static checker
# step 1: dump vm state info for the test machine
# step 2: check all benchmark jsons are downloaded into guest vm in benchmark folder
# step 3: if machine type matches than compare corresponding json files using static checker
# step 4: compare the difference with known false postives and if found throw a error

# currently supports qemu-kvm/qemu-kvm-rhev for x86_64,ppc64le,aarch64
# append new arch to SUPPORTED_ARCHITECTURES
# returns 0 for pass or non zero for errors

import sys, subprocess, logging, json, os
import argparse
from logging import DEBUG, INFO, WARN, ERROR, CRITICAL


MYDIR = os.path.dirname(__file__)
BENCHMARKSPATH = os.path.join(MYDIR, 'benchmarks')
VMSTATESPATH = os.path.join(MYDIR, 'vmstates')
DIFFPATH = os.path.join(MYDIR, 'diff')
QEMULOCATION = '/usr/libexec/qemu-kvm'
ARCHITECTURE = 'x86_64'
FALSE_POSITIVES = 'false_positives'
BASELINE = 'baseline'
CHECKERPATH = ''

SUPPORTED_ARCHITECTURE = ["x86_64", "aarch64", "ppc64le"]

logger = logging.getLogger('run-static-checker')
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
logger.addHandler(ch)


# record of actual errors found
taint = {}
total_errors = 0


def bump_taint(src, dest, error):
    global taint
    global total_errors

    if src in taint:
        temp = taint[src]
        if dest in temp:
            details = temp[dest]

            old_number = details['num_of_errors']
            details['num_of_errors'] = old_number + 1
            total_errors = total_errors + 1
            old_list = details['list_of_errors']
            old_list.append(error)
            details['list_of_errors'] = old_list
            temp[dest] = details
            taint[src] = temp
        else:
            temp = {}
            temp1 = {}
            temp['num_of_errors'] = 1
            total_errors = total_errors + 1
            temp['list_of_errors'] = [error]
            temp1[dest] = temp
            taint[src] = temp1
    else:
        temp = {}
        temp1 = {}
        total_errors = total_errors + 1
        temp['num_of_errors'] = 1
        temp['list_of_errors'] = [error]
        temp1[dest] = temp
        taint[src] = temp1


def byte_to_string(thestring):
    # python 2 has str and unicode whose parent class is basestring
    # python 3 only has str and bytes whose parent class is object
    try:
        basestring
        return thestring
    except NameError:
        return thestring.decode('utf-8')


def call_subprocess(cmd):
    try:
        child = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT)
        out, err = child.communicate()
        # python2/3 compatible
        if err:
            err = byte_to_string(err)

        if out:
            out = byte_to_string(out)

        exit_code = child.returncode
        return exit_code, out
    except:
        logger.error('Error in running subprocess:' + str(cmd))
        logger.error(err)
        sys.exit(1)


def check_inventory():
    # logger.info(BENCHMARKPATH)
    if (not os.path.isdir(BENCHMARKSPATH)):
        logger.error('benchmark directory not found at:' + str(BENCHMARKSPATH) + '.Exiting...')
        sys.exit(1)

    if (not os.path.isdir(VMSTATESPATH)):
        logger.error('VM states folder not found at:' + str(VMSTATESPATH) + '.Exiting...')
        sys.exit(1)

    if(not os.path.exists(CHECKERPATH)):
        logger.error('test script not found at:' + str(CHECKERPATH) + '.Exiting...')
        sys.exit(1)

    if (not os.path.isdir(DIFFPATH)):
        logger.error('diff folder not found at:' + str(DIFFPATH) + '.Exiting...')
        sys.exit(1)

    global QEMULOCATION
    if (not os.path.exists(QEMULOCATION)):
        logger.info('qemu-kvm binary not found at:'+str(QEMULOCATION)+'.Switching path to /usr/bin/qemu-kvm')
        QEMULOCATION = "/usr/bin/qemu-kvm"
        if(not os.path.exists(QEMULOCATION)):
            logger.error('qemu-kvm binary not found at:' + str(QEMULOCATION) + '.Exiting...')
            sys.exit(1)


def dump_current_vmstates(one_machine_type):
    # get all supported machine types from current vm
    cmd = [QEMULOCATION, '--machine', 'help']
    code, output = call_subprocess(cmd)
    if (int(code) != 0):
        logger.error('Error in getting supported machine types: ' + str(cmd))
        logger.error('Exiting...')
        sys.exit(1)

    # parse output
    output = output.splitlines()
    output = output[1:]  # remove the first line
    m_types = []
    for eachline in output:
        parts = eachline.split(' ')
        m_types.append(parts[0])

    if one_machine_type:
        m_types = [one_machine_type]

    for machine in m_types:
        dump_filename = machine + '.json'
        dump_path = os.path.join(VMSTATESPATH, dump_filename)

        # -nographic command helps with fedora error gtk not implemented
        # all output is directed to i/o console
        cmd = [QEMULOCATION, '-nographic', '-M', machine, '-dump-vmstate', dump_path]
        exit_code, output = call_subprocess(cmd)
        if(int(exit_code) != 0):
            logger.error('Error dumping (' + str(cmd) + ') vmstate info:'+str(output))
            logger.error('deleting JSON file:'+str(dump_path))
            os.remove(dump_path)

    # by listing directory we also double check if JSONs were generated or not
    list_of_curr_vmstates = os.listdir(VMSTATESPATH)
    if (len(list_of_curr_vmstates) == 0):
        logger.error('No vmstates JSON dumps created.Exiting...')
        sys.exit(1)

    logger.info('\nList of machine definitions supported by current vm:')
    logger.info(list_of_curr_vmstates)
    return list_of_curr_vmstates


def runStaticChecker(src_json_path, dest_json_path, src_host, dest_host, machine_type):
    logger.info('Testing migration:' + src_host + ' --> ' + dest_host + ' for machine type:' + str(machine_type))
    cmd = [CHECKERPATH, '-s', src_json_path, '-d', dest_json_path]
    m_type = machine_type.replace('json', 'txt')
    error_filename = 'diff_'+src_host+'_to_' + dest_host + '_' + m_type
    error_path = os.path.join(DIFFPATH, error_filename)
    exit_code, output = call_subprocess(cmd)
    if (int(exit_code) != 0):
        logger.error('Found '+str(exit_code)+' issues.')
        error_log = open(error_path, 'a')
        error_log.write(output)
        error_log.close()
        remove_false_positives(output, src_host, dest_host)
    else:
        logger.info('Found 0 issues')


def remove_false_positives(output, src_host, dest_host):
    fp_name = 'fp_'+str(src_host)+'_to_'+str(dest_host) + '.txt'
    fp_directory = os.path.join(BENCHMARKSPATH, FALSE_POSITIVES)
    fp_path = os.path.join(fp_directory, fp_name)
    if os.path.isfile(fp_path):
        logger.info('Comparing with previous false_positives:'+str(fp_path))
        with open(fp_path) as fp:
            prev_fp = fp.read().splitlines()

        curr_results = output.splitlines()
        found = False
        for eachLine in curr_results:
            if eachLine not in prev_fp:
                logger.error('\nError found:'+str(eachLine))
                bump_taint(src_host, dest_host, eachLine)
                found = True

        if not found:
            logger.info('Issues match false positives. No error found')
    else:
        logger.error('No false positive file found:'+str(fp_path))


def matchingBenchmarks(list_of_curr_vmstates, src_host):
    logger.info('\nMapping benchmarks to current dumps')

    baseline = os.path.join(BENCHMARKSPATH, BASELINE)
    # baseline = ./benchmarks/qemu-kvm-rhev/x86_64/baseline

    list_of_os = os.listdir(baseline)
    # list_of_os = [f24,f25,26]

    for older_linux in list_of_os:
        older_linux_path = os.path.join(baseline, older_linux)
        # old_linux_path = ./benchmarks/qemu-kvm-rhev/x86_64/baseline/rhel74

        # skip empty rhel folder like rhel70
        if(len(os.listdir(older_linux_path)) != 0):
            list_of_vmstates = os.listdir(older_linux_path)
            logger.info("\nFolder:"+older_linux + " contains benchmarks:"+str(list_of_vmstates))
            for prev_vmstate in list_of_vmstates:
                # check if vmstate matches previous benchmarks
                for curr_vmstate in list_of_curr_vmstates:
                    if curr_vmstate in prev_vmstate:
                        logger.info("\nCurrent vmstate:"+str(curr_vmstate) + ' matches benchmark:' + str(prev_vmstate) + ' in folder:'+str(older_linux))
                        src_json_path = os.path.join(VMSTATESPATH, curr_vmstate)
                        dest_json_path = os.path.join(older_linux_path, prev_vmstate)
                        if os.path.isfile(src_json_path) and os.path.isfile(dest_json_path):
                            # check backward migration
                            runStaticChecker(src_json_path, dest_json_path, src_host, older_linux, curr_vmstate)
                            # check forward migration
                            runStaticChecker(dest_json_path, src_json_path, older_linux, src_host, curr_vmstate)
                        else:
                            logger.warn('vmstate json dump does not exist:' + str(src_json_path) + ' or ' + str(dest_json_path))
        else:
            logger.info('\nSkipping empty '+str(older_linux) + ' folder')


def main():
    parser = argparse.ArgumentParser(prog='run_static_checker',
            description='wrapper over static-checker')
    parser.add_argument('--t', metavar='which test', required=True,
            help='test name: static-checker-up',
            action='store', dest='test_name')
    parser.add_argument('--v', metavar='test OS', required=True,
            help='test/host OS name: rhel74/F24',
            action='store', dest='test_os')
    parser.add_argument('--q', metavar='qemu type', required=True,
            help='enter either: qemu-kvm/qemu-kvm-rhev',
            action='store', dest='qemu_type')
    parser.add_argument('--a', metavar='architecture',
            help='enter architecture: x86_64/aarch64/ppc64le/P9/Z',
            action='store', dest='arch', choices=['x86_64', 'aarch64', 'ppc64le', 'P9', 'Z'])
    parser.add_argument('--m', metavar='machineType',
            help='input one machine type', dest='m_type')
    args = parser.parse_args()
    # logger.info(args)
    # retrieve the system architecture
    cmd = ['uname', '-m']
    code, output = call_subprocess(cmd)
    if (int(code) != 0):
        logger.error('Error in retrieving system architecture: ' + str(cmd))
        logger.error('Exiting...')
        sys.exit(1)
    else:
        output = output.strip()
        if output not in SUPPORTED_ARCHITECTURE:
            logger.error('Unsupported architecture. '+str(output)+' not in '+str(SUPPORTED_ARCHITECTURE)+' Exiting...')
            sys.exit(1)
        else:
            global ARCHITECTURE
            ARCHITECTURE = str(output)
            logger.info('Architecture found:'+str(ARCHITECTURE))


    global BENCHMARKSPATH
    BENCHMARKSPATH = os.path.join(BENCHMARKSPATH, args.qemu_type)
    BENCHMARKSPATH = os.path.join(BENCHMARKSPATH, ARCHITECTURE)

    global CHECKERPATH
    CHECKERPATH = os.path.join(MYDIR, args.test_name)

    check_inventory()
    supported_machine_types = dump_current_vmstates(args.m_type)
    matchingBenchmarks(supported_machine_types, args.test_os)

    global taint
    if len(taint) != 0:
        logger.info(taint)

    global total_errors
    return total_errors


if __name__ == '__main__':
    sys.exit(main())
