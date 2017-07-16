import time
import json
import base64
import hashlib
import binascii
import urlparse
import textwrap
import platform

import requests
import OpenSSL
import cryptography
from structlog import get_logger

import __version__ as sewer_version


class ACMEclient(object):
    """
    todo: improve documentation.

    usage:
        import sewer
        dns_class = sewer.CloudFlareDns(CLOUDFLARE_DNS_ZONE_ID='random',
                                        CLOUDFLARE_EMAIL='example@example.com',
                                        CLOUDFLARE_API_KEY='nsa-grade-api-key')

        1. to create a new certificate.
        client = ACMEclient(domain_name='example.com',
                            dns_class=dns_class)
        certificate = client.cert()
        certificate_key = client.certificate_key
        account_key = client.account_key

        with open('certificate.crt', 'w') as certificate_file:
            certificate_file.write(certificate)

        with open('certificate.key', 'w') as certificate_key_file:
            certificate_key_file.write(certificate_key)


        2. to renew a certificate:
        with open('account_key.key', 'r') as account_key_file:
            account_key = account_key_file.read()

        client = ACMEclient(domain_name='example.com',
                            dns_class=dns_class,
                            account_key=account_key)
        certificate = client.renew()
        certificate_key = client.certificate_key

    todo:
        - handle exceptions
    """

    def __init__(
            self,
            domain_name,
            dns_class,
            registration_recovery_email=None,
            account_key=None,
            bits=2048,
            digest='sha256',
            ACME_REQUEST_TIMEOUT=65,
            ACME_CHALLENGE_WAIT_PERIOD=4,
            GET_NONCE_URL="https://acme-v01.api.letsencrypt.org/directory",
            ACME_CERTIFICATE_AUTHORITY_URL="https://acme-v01.api.letsencrypt.org",
            ACME_CERTIFICATE_AUTHORITY_TOS='https://letsencrypt.org/documents/LE-SA-v1.1.1-August-1-2016.pdf',
            ACME_CERTIFICATE_AUTHORITY_CHAIN='https://letsencrypt.org/certs/lets-encrypt-x3-cross-signed.pem'
    ):

        self.logger = get_logger(__name__).bind(
            client_name=self.__class__.__name__)

        self.domain_name = domain_name
        self.dns_class = dns_class
        self.registration_recovery_email = registration_recovery_email
        self.bits = bits
        self.digest = digest
        self.ACME_REQUEST_TIMEOUT = ACME_REQUEST_TIMEOUT
        self.ACME_CHALLENGE_WAIT_PERIOD = ACME_CHALLENGE_WAIT_PERIOD
        self.GET_NONCE_URL = GET_NONCE_URL
        self.ACME_CERTIFICATE_AUTHORITY_URL = ACME_CERTIFICATE_AUTHORITY_URL
        self.ACME_CERTIFICATE_AUTHORITY_TOS = ACME_CERTIFICATE_AUTHORITY_TOS
        self.ACME_CERTIFICATE_AUTHORITY_CHAIN = ACME_CERTIFICATE_AUTHORITY_CHAIN
        self.User_Agent = self.get_user_agent()
        self.certificate_key = self.create_certificate_key()
        self.csr = self.create_csr()
        self.certificate_chain = self.get_certificate_chain()

        if not account_key:
            self.account_key = self.create_account_key()
            self.PRIOR_REGISTERED = False
        else:
            self.account_key = account_key
            self.PRIOR_REGISTERED = True

        self.logger = self.logger.bind(
            sewer_client_name=self.__class__.__name__,
            sewer_client_version=sewer_version.__version__,
            domain_name=self.domain_name,
            ACME_CERTIFICATE_AUTHORITY_URL=self.ACME_CERTIFICATE_AUTHORITY_URL)

        # for staging/test, use:
        # GET_NONCE_URL="https://acme-staging.api.letsencrypt.org/directory",
        # ACME_CERTIFICATE_AUTHORITY_URL="https://acme-staging.api.letsencrypt.org"

    def get_user_agent(self):
        # TODO: add the sewer-acme versionto the User-Agent
        return "python-requests/{requests_version} ({system}: {machine}) sewer {sewer_version} ({sewer_url})".format(
            requests_version=requests.__version__,
            system=platform.system(),
            machine=platform.machine(),
            sewer_version=sewer_version.__version__,
            sewer_url=sewer_version.__url__)

    def create_account_key(self):
        self.logger.info('create_account_key')
        return self.create_key()

    def create_certificate_key(self):
        self.logger.info('create_certificate_key')
        return self.create_key()

    def create_key(self, key_type=OpenSSL.crypto.TYPE_RSA):
        key = OpenSSL.crypto.PKey()
        key.generate_key(key_type, self.bits)
        private_key = OpenSSL.crypto.dump_privatekey(
            OpenSSL.crypto.FILETYPE_PEM, key)
        return private_key

    def create_csr(self):
        self.logger.info('create_csr')
        SAN = 'DNS:{0}'.format(self.domain_name).encode('utf8')
        X509Req = OpenSSL.crypto.X509Req()
        X509Req.get_subject().CN = self.domain_name
        X509Req.add_extensions([
            OpenSSL.crypto.X509Extension(
                'subjectAltName'.encode('utf8'), critical=False, value=SAN)
        ])
        pk = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM,
                                            self.certificate_key)
        X509Req.set_pubkey(pk)
        X509Req.set_version(2)
        X509Req.sign(pk, self.digest)
        return OpenSSL.crypto.dump_certificate_request(
            OpenSSL.crypto.FILETYPE_ASN1, X509Req)

    def get_certificate_chain(self):
        self.logger.info('get_certificate_chain')
        url = self.ACME_CERTIFICATE_AUTHORITY_CHAIN
        headers = {'User-Agent': self.User_Agent}
        get_certificate_chain_response = requests.get(
            url, timeout=self.ACME_REQUEST_TIMEOUT, headers=headers)
        certificate_chain = get_certificate_chain_response.content.decode(
            'utf8')
        self.logger.info(
            'get_certificate_chain_response',
            status_code=get_certificate_chain_response.status_code)
        return certificate_chain

    def calculate_safe_base64(self, un_encoded_data):
        return base64.urlsafe_b64encode(un_encoded_data).decode('utf8').rstrip(
            '=')

    def sign_message(self, message):
        self.logger.info('sign_message')
        pk = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM,
                                            self.account_key)
        return OpenSSL.crypto.sign(pk, message.encode('utf8'), self.digest)

    def get_acme_header(self):
        self.logger.info('get_acme_header')
        private_key = cryptography.hazmat.primitives.serialization.load_pem_private_key(
            self.account_key,
            password=None,
            backend=cryptography.hazmat.backends.default_backend())
        public_key_public_numbers = private_key.public_key().public_numbers()

        # private key public exponent in hex format
        exponent = "{0:x}".format(public_key_public_numbers.e)
        exponent = "0{0}".format(exponent) if len(exponent) % 2 else exponent
        # private key modulus in hex format
        modulus = "{0:x}".format(public_key_public_numbers.n)
        header = {
            "alg": "RS256",
            "jwk": {
                "e":
                self.calculate_safe_base64(
                    binascii.unhexlify(exponent.encode('utf8'))),
                "kty":
                "RSA",
                "n":
                self.calculate_safe_base64(
                    binascii.unhexlify(modulus.encode('utf8')))
            }
        }
        return header

    def make_signed_acme_request(self, url, payload):
        self.logger.info('make_signed_acme_request')
        payload64 = self.calculate_safe_base64(
            json.dumps(payload).encode('utf8'))
        protected = self.get_acme_header()

        headers = {'User-Agent': self.User_Agent}
        response = requests.get(
            self.GET_NONCE_URL,
            timeout=self.ACME_REQUEST_TIMEOUT,
            headers=headers)
        nonce = response.headers['Replay-Nonce']
        protected["nonce"] = nonce

        protected64 = self.calculate_safe_base64(
            json.dumps(protected).encode('utf8'))
        signature = self.sign_message(message="{0}.{1}".format(
            protected64, payload64))
        data = json.dumps({
            "protected": protected64,
            "payload": payload64,
            "signature": self.calculate_safe_base64(signature)
        })
        headers = {'User-Agent': self.User_Agent}
        response = requests.post(
            url,
            data=data.encode('utf8'),
            timeout=self.ACME_REQUEST_TIMEOUT,
            headers=headers)
        return response

    def acme_register(self):
        """
        Register using a customers account_key.
        This method should only be called if self.PRIOR_REGISTERED == False
        """
        self.logger.info('acme_register')
        if self.registration_recovery_email:
            payload = {
                "resource": "new-reg",
                "agreement": self.ACME_CERTIFICATE_AUTHORITY_TOS,
                "contact":
                ["mailto:{0}".format(self.registration_recovery_email)]
            }
        else:
            payload = {
                "resource": "new-reg",
                "agreement": self.ACME_CERTIFICATE_AUTHORITY_TOS
            }
        url = urlparse.urljoin(self.ACME_CERTIFICATE_AUTHORITY_URL,
                               '/acme/new-reg')
        acme_register_response = self.make_signed_acme_request(
            url=url, payload=payload)
        self.logger.info(
            'acme_register_response',
            status_code=acme_register_response.status_code,
            response=acme_register_response.json())
        return acme_register_response

    def get_challenge(self):
        self.logger.info('get_challenge')
        payload = {
            "resource": "new-authz",
            "identifier": {
                "type": "dns",
                "value": self.domain_name
            }
        }
        url = urlparse.urljoin(self.ACME_CERTIFICATE_AUTHORITY_URL,
                               '/acme/new-authz')
        challenge_response = self.make_signed_acme_request(
            url=url, payload=payload)
        self.logger.info(
            'get_challenge_response',
            status_code=challenge_response.status_code,
            response=challenge_response.json())

        for i in challenge_response.json()['challenges']:
            if i['type'] == 'dns-01':
                dns_challenge = i
        dns_token = dns_challenge['token']
        dns_challenge_url = dns_challenge['uri']

        return dns_token, dns_challenge_url

    def get_keyauthorization(self, dns_token):
        self.logger.info('get_keyauthorization')
        acme_header_jwk_json = json.dumps(
            self.get_acme_header()['jwk'],
            sort_keys=True,
            separators=(',', ':'))
        acme_thumbprint = self.calculate_safe_base64(
            hashlib.sha256(acme_header_jwk_json.encode('utf8')).digest())
        acme_keyauthorization = "{0}.{1}".format(dns_token, acme_thumbprint)
        base64_of_acme_keyauthorization = self.calculate_safe_base64(
            hashlib.sha256(acme_keyauthorization.encode("utf8")).digest())

        return acme_keyauthorization, base64_of_acme_keyauthorization

    def notify_acme_challenge_set(self, acme_keyauthorization,
                                  dns_challenge_url):
        self.logger.info('notify_acme_challenge_set')
        payload = {
            "resource": "challenge",
            "keyAuthorization": "{0}".format(acme_keyauthorization)
        }
        notify_acme_challenge_set_response = self.make_signed_acme_request(
            dns_challenge_url, payload)
        self.logger.info(
            'notify_acme_challenge_set_response',
            status_code=notify_acme_challenge_set_response.status_code,
            response=notify_acme_challenge_set_response.json())
        return notify_acme_challenge_set_response

    def check_challenge_status(self, dns_record_id, dns_challenge_url,
                               base64_of_acme_keyauthorization):
        self.logger.info('check_challenge')
        time.sleep(self.ACME_CHALLENGE_WAIT_PERIOD)
        number_of_checks = 0
        maximum_number_of_checks_allowed = 15
        while True:
            try:
                headers = {'User-Agent': self.User_Agent}
                check_challenge_status_response = requests.get(
                    dns_challenge_url,
                    timeout=self.ACME_REQUEST_TIMEOUT,
                    headers=headers)
                challenge_status = check_challenge_status_response.json()[
                    'status']
                number_of_checks = number_of_checks + 1
                self.logger.info(
                    'check_challenge_status_response',
                    status_code=check_challenge_status_response.status_code,
                    response=check_challenge_status_response.json(),
                    number_of_checks=number_of_checks)
                if number_of_checks > maximum_number_of_checks_allowed:
                    raise StopIteration(
                        "Number of checks done is {0} which is greater than the maximum allowed of {1}.".
                        format(number_of_checks,
                               maximum_number_of_checks_allowed))
            except Exception as e:
                self.logger.info('check_challenge', error=str(e))
                break
            if challenge_status == "pending":
                time.sleep(self.ACME_CHALLENGE_WAIT_PERIOD)
            elif challenge_status == "valid":
                self.dns_class.delete_dns_record(
                    self.domain_name, base64_of_acme_keyauthorization)
                break
        return check_challenge_status_response

    def get_certicate(self):
        self.logger.info('get_certicate')
        payload = {
            "resource": "new-cert",
            "csr": self.calculate_safe_base64(self.csr)
        }
        url = urlparse.urljoin(self.ACME_CERTIFICATE_AUTHORITY_URL,
                               '/acme/new-cert')
        get_certicate_response = self.make_signed_acme_request(url, payload)
        base64encoded_cert = base64.b64encode(
            get_certicate_response.content).decode('utf8')
        sixty_four_width_cert = textwrap.wrap(base64encoded_cert, 64)
        certificate = '\n'.join(sixty_four_width_cert)

        pem_certificate = """-----BEGIN CERTIFICATE-----\n{0}\n-----END CERTIFICATE-----\n""".format(
            certificate)
        pem_certificate_and_chain = pem_certificate + self.certificate_chain
        return pem_certificate_and_chain

    def just_get_me_a_certificate(self):
        self.logger.info('just_get_me_a_certificate')
        if not self.PRIOR_REGISTERED:
            self.acme_register()
        dns_token, dns_challenge_url = self.get_challenge()
        acme_keyauthorization, base64_of_acme_keyauthorization = self.get_keyauthorization(
            dns_token)
        create_cloudflare_dns_record_response = self.dns_class.create_dns_record(
            self.domain_name, base64_of_acme_keyauthorization)
        self.notify_acme_challenge_set(acme_keyauthorization, dns_challenge_url)
        dns_record_id = create_cloudflare_dns_record_response.json()['result'][
            'id']
        self.check_challenge_status(dns_record_id, dns_challenge_url,
                                    base64_of_acme_keyauthorization)
        certificate = self.get_certicate()

        return certificate

    def cert(self):
        """
        convenience method to get a certificate without much hassle
        """
        return self.just_get_me_a_certificate()

    def certificate(self):
        """
        convenience method to get a certificate without much hassle
        """
        return self.just_get_me_a_certificate()

    def renew(self):
        """
        renews a certificate.
        A renewal is actually just getting a new certificate.
        An issuance request counts as a renewal if it contains the exact same set of hostnames as a previously issued certificate.
            https://letsencrypt.org/docs/rate-limits/
        """
        return self.just_get_me_a_certificate()
