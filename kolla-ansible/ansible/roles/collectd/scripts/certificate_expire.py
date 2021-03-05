import copy
import os
import re
import collectd
from OpenSSL import crypto
from datetime import datetime
from datetime import date


CERTS_PATH = ["{{ Cert_dir }}"]
CERT_BEGIN_DELIMITER = "-----BEGIN CERTIFICATE-----"
CERT_END_DELIMITER = "-----END CERTIFICATE-----"
CERT_ORIGINAL_LINE_SEPARATOR = "\n"
CERT_TEMPORARY_LINE_SEPARATOR = "&"
DATA = {"data": []}
CERT_INFO = []


def get_certificates(certs_path):
    return {
        cert: get_cert_list_from_file(cert) for cert in os.listdir(certs_path)
        if os.path.isfile(os.path.join(certs_path, cert))
    }


def get_list_of_cert_info(certificates):
    for filename, content in certificates.items():
        CERT_INFO.extend(get_cert_info(filename, content))
    return CERT_INFO


def get_cert_info(filename, content):
    return [
        {
            "{{ '{#'  }}FILENAME}": filename,
            "{{ '{#'  }}INDEX}": index + 1,
            "{{ '{#'  }}DAYS}": get_remaining_days(cert)
        }
        for index, cert in enumerate(content)
    ]


def get_certificate_as_string(filename):
    for certs in CERTS_PATH:
        try:
            with open(certs + filename, "r") as cert:
                return cert.read()
        except IOError:
            pass


def join_cert_lines(cert_str):
    return cert_str.replace(CERT_ORIGINAL_LINE_SEPARATOR, CERT_TEMPORARY_LINE_SEPARATOR)


def get_cert_list_from_file(filename):
    regex = "{}[^-]*{}".format(CERT_BEGIN_DELIMITER, CERT_END_DELIMITER)
    cert_as_string = get_certificate_as_string(filename)
    modified_cert = join_cert_lines(cert_as_string)
    list_of_certs = re.findall(regex, modified_cert)
    return list_of_certs


def split_cert_string(cert_str):
    return cert_str.replace(CERT_TEMPORARY_LINE_SEPARATOR, CERT_ORIGINAL_LINE_SEPARATOR)


def get_remaining_days(cert):
    original_cert = split_cert_string(cert)
    cert_obj = crypto.load_certificate(crypto.FILETYPE_PEM, original_cert)
    exp_datetime = (datetime.strptime(cert_obj.get_notAfter().decode('ascii'), "%Y%m%d%H%M%SZ"))
    exp_days = date(exp_datetime.year, exp_datetime.month, exp_datetime.day) - date.today()
    return exp_days.days


def modify_cert_info(cert_info):
    cert_info_copy = copy.deepcopy(cert_info)
    for i in cert_info_copy:
        del i["{{ '{#'  }}DAYS}"]
        DATA["data"].append(i)


def process_cert_info():
    for certs in CERTS_PATH:
        if not os.listdir(certs):
            pass
        else:
            certificates = get_certificates(certs)
            get_list_of_cert_info(certificates)
    modify_cert_info(CERT_INFO)


def push_cert_info():
    process_cert_info()
    for details in CERT_INFO:
        filename = details["{{ '{#'  }}FILENAME}"].replace(".", "_").replace("-", "_")
        index = "_"+str(details["{{ '{#'  }}INDEX}"])
        days = details["{{ '{#'  }}DAYS}"]
        dispatch_values(filename, index, days)


def dispatch_values(filename, index, days):
    metric = collectd.Values(type="counter")
    metric.plugin = "crt"
    metric.plugin_instance = filename+index
    metric.values = [days]
    metric.dispatch()


if __name__ != "__main__":
    collectd.register_read(push_cert_info)
