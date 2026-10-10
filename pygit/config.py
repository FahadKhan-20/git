import os
import re


def read_config(path):
    config = {}
    if not os.path.exists(path):
        return config
    section = None
    with open(path, "r") as f:
        for line in f:
            line_str = line.strip()
            if not line_str or line_str.startswith("#") or line_str.startswith(";"):
                continue
            if line_str.startswith("[") and line_str.endswith("]"):
                sec_content = line_str[1:-1].strip()
                m = re.match(r'^([\w\-]+)(?:\s+"([^"]+)")?$', sec_content)
                if m:
                    sec_name = m.group(1)
                    sub_name = m.group(2)
                    if sub_name:
                        section = (sec_name, sub_name)
                    else:
                        section = (sec_name, None)
                else:
                    section = (sec_content, None)
                if section not in config:
                    config[section] = {}
            elif section is not None and "=" in line_str:
                k, v = line_str.split("=", 1)
                config[section][k.strip()] = v.strip()
    return config


def write_config(path, config):
    with open(path, "w") as f:
        for section, values in config.items():
            sec_name, sub_name = section
            if sub_name:
                f.write(f'[{sec_name} "{sub_name}"]\n')
            else:
                f.write(f'[{sec_name}]\n')
            for k, v in values.items():
                f.write(f"\t{k} = {v}\n")
            f.write("\n")
