import logging


class BaseAuthProvider(object):
    def __init__(self, auth_type, LOG_LEVEL="INFO"):
        self.LOG_LEVEL = LOG_LEVEL
        self.dns_provider_name = self.__class__.__name__

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(self.LOG_LEVEL)
        if not self.logger.hasHandlers():
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        self.auth_type = auth_type

    def log_response(self, response):
        """
        renders a python-requests response as json or as a string
        """
        try:
            log_body = response.json()
        except ValueError:
            log_body = response.content
        return log_body

    def get_identifier_auth(self, authorization_response, url):
        domain = authorization_response["identifier"]["value"]
        wildcard = authorization_response.get("wildcard")
        if wildcard:
            domain = "*." + domain

        for i in authorization_response["challenges"]:
            if i["type"] == self.auth_type:
                challenge = i
                challenge_token = challenge["token"]
                challenge_url = challenge["url"]

                return {
                    "domain": domain,
                    "url": url,
                    "wildcard": wildcard,
                    "token": challenge_token,
                    "challenge_url": challenge_url,
                }

    def create_auth_record(self, name, value):
        raise NotImplementedError("create_auth_record method must be implemented.")

    def delete_auth_record(self, name, value):
        raise NotImplementedError("delete_auth_record method must be implemented.")

    def fulfill_authorization(self, identifier_auth, value, acme_keyauthorization):
        """
        TODO: docs here
        """
        name = identifier_auth["domain"]
        self.create_auth_record(name, value)

        responder = {
            "challenge_url": identifier_auth["challenge_url"],
            "acme_keyauthorization": acme_keyauthorization,
            "authorization_url": identifier_auth["url"],
        }
        cleanup = {"name": name, "value": value}
        return (responder, cleanup)

    def cleanup(self, record):
        self.delete_auth_record(record["name"], record["value"])


class BaseDns(BaseAuthProvider):
    def __init__(self):
        super(BaseDns, self).__init__("dns-01")

    def create_auth_record(self, name, value):
        return self.create_dns_record(name, value)

    def delete_auth_record(self, name, value):
        return self.delete_dns_record(name, value)

    def create_dns_record(self, domain_name, domain_dns_value):
        """
        Method that creates/adds a dns TXT record for a domain/subdomain name on
        a chosen DNS provider.

        :param domain_name: :string: The domain/subdomain name whose dns record ought to be
            created/added on a chosen DNS provider.
        :param domain_dns_value: :string: The value/content of the TXT record that will be
            created/added for the given domain/subdomain

        This method should return None

        Basic Usage:
            If the value of the `domain_name` variable is example.com and the value of
            `domain_dns_value` is HAJA_4MkowIFByHhFaP8u035skaM91lTKplKld
            Then, your implementation of this method ought to create a DNS TXT record
            whose name is '_acme-challenge' + '.' + domain_name + '.' (ie: _acme-challenge.example.com. )
            and whose value/content is HAJA_4MkowIFByHhFaP8u035skaM91lTKplKld

            Using a dns client like dig(https://linux.die.net/man/1/dig) to do a dns lookup should result
            in something like:
                dig TXT _acme-challenge.example.com
                ...
                ;; ANSWER SECTION:
                _acme-challenge.example.com. 120 IN TXT "HAJA_4MkowIFByHhFaP8u035skaM91lTKplKld"
                _acme-challenge.singularity.brandur.org. 120 IN TXT "9C0DqKC_4MkowIFByHhFaP8u0Zv4z7Wz2IHM91lTKec"
            Optionally, you may also use an online dns client like: https://toolbox.googleapps.com/apps/dig/#TXT/

            Please consult your dns provider on how/format of their DNS TXT records.
            You may also want to consult the cloudflare DNS implementation that is found in this repository.
        """
        raise NotImplementedError("create_dns_record method must be implemented.")

    def delete_dns_record(self, domain_name, domain_dns_value):
        """
        Method that deletes/removes a dns TXT record for a domain/subdomain name on
        a chosen DNS provider.

        :param domain_name: :string: The domain/subdomain name whose dns record ought to be
            deleted/removed on a chosen DNS provider.
        :param domain_dns_value: :string: The value/content of the TXT record that will be
            deleted/removed for the given domain/subdomain

        This method should return None
        """
        raise NotImplementedError("delete_dns_record method must be implemented.")


class BaseHttp(BaseAuthProvider):
    def __init__(self):
        super(BaseHttp, self).__init__("http-01")


class CertbotishProvider(BaseHttp):
    def create_auth_record(self, name, value):
        with open("/path/to/www/html/.well-known/{name}", "w") as fp:
            fp.write(value)

    def delete_auth_record(self, name, value):
        import os

        os.unlink("/path/to/www/html/.well-known/{name}")
