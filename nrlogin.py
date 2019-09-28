from nornir import InitNornir
import sys
import interactive

#Interactive ssh with netmiko connection
#interactive.py found in paramiko demo directory

def netmiko_interactive(task):
    net_connect = task.host.get_connection("netmiko", task.nornir.config)
    print(net_connect.find_prompt(),end='')
    sys.stdout.flush()
    interactive.interactive_shell(net_connect.remote_conn)
    
if len(sys.argv) == 2:
    hostname = sys.argv[1]
else:
    print("Hostname required.")
    sys.exit(1)

nr = InitNornir('config.yaml')
nr = nr.filter(name=hostname)

results = nr.run(task=netmiko_interactive)
