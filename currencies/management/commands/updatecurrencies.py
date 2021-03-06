# -*- coding: utf-8 -*-
from decimal import Decimal
from django.conf import settings

from .currencies import Command as CurrencyCommand
from ...models import Currency


class Command(CurrencyCommand):
    help = "Update the db currencies with the live exchange rates"

    def add_arguments(self, parser):
        """Add command arguments"""
        parser.add_argument(self._source_param, **self._source_kwargs)
        parser.add_argument('--base', '-b', action='store',
            help=   'Supply the base currency as code or a settings variable name. '
                    'The default is taken from settings CURRENCIES_BASE or SHOP_DEFAULT_CURRENCY, '
                    'or the db, otherwise USD')

    def get_base(self, option):
        """
        Parse the base command option. Can be supplied as a 3 character code or a settings variable name
        If base is not supplied, looks for settings CURRENCIES_BASE and SHOP_DEFAULT_CURRENCY
        """
        if isinstance(option, str) and option.isupper():
            if len(option) == 3:
                return option, True
            else:
                return getattr(settings, option), True
        else:
            for attr in ('CURRENCIES_BASE', 'SHOP_DEFAULT_CURRENCY'):
                try:
                    return getattr(settings, attr), True
                except AttributeError:
                    continue
            return 'USD', False

    def handle(self, *args, **options):
        """Handle the command"""
        # get the command arguments
        self.verbose = int(options.get('verbosity', 0))
        base, base_was_arg = self.get_base(options['base'])

        # Import the CurrencyHandler and get an instance
        handler = self.get_handler(options)

        # See if the db already has a base currency
        try:
            db_base_obj = Currency._default_manager.get(is_base=True)
            db_base = db_base_obj.code
        except Currency.DoesNotExist:
            db_base = None

        if db_base and not base_was_arg:
            base = db_base
            base_obj = db_base_obj
            base_in_db = True
        else:
            # see if the argument base currency exists in the db
            try:
                base_in_db = True
                base_obj = Currency._default_manager.get(code=base)
            except Currency.DoesNotExist:
                base_in_db = False
                self.stderr.write(
                    "Base currency %r does not exist in the db! Rates will be erroneous without it." % base)

        if db_base and base_was_arg and base_in_db and (db_base != base):
            self.info("Changing db base currency from %s to %s" % (db_base, base))
            db_base_obj.is_base = False
            db_base_obj.save()
            base_obj.is_base = True
            base_obj.save()
        elif (not db_base) and base_in_db:
            base_obj.is_base = True
            base_obj.save()

        self.info("Using %s as base for all currencies" % base)
        self.info("Getting currency rates from %s" % handler.endpoint)

        obj = None
        for obj in Currency._default_manager.all():
            try:
                rate = handler.get_ratefactor(base, obj.code)
            except AttributeError:
                self.stderr.write("This source does not provide currency rate information")
                return
            if not rate:
                self.stderr.write("Could not find rates for %s (%s)" % (obj.name, obj.code))
                continue

            factor = rate.quantize(Decimal(".0001"))
            if obj.factor != factor:
                kwargs = {'factor': factor}
                try:
                    datetime = handler.get_ratetimestamp(base, obj.code)
                except AttributeError:
                    datetime = None
                if datetime:
                    obj.info.update({'RateUpdate': datetime.isoformat()})
                    kwargs['info'] = obj.info
                    update_str = ", updated at %s" % datetime.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    update_str = ""

                self.info("Updating %s rate to %f%s" % (obj, factor, update_str))

                Currency._default_manager.filter(pk=obj.pk).update(**kwargs)
        if not obj:
            self.stderr.write("No currencies found in the db to update; try the currencies command!")
