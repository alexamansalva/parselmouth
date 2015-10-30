#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" Parseltongue - Main Package Entry Point

This package serves as the base interface between Chartbeat worker and
services and third-party ad servers.
"""

# Future-proof
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

# Standard Library Imports
import logging

# Third Party Library Imports
from cjson import decode

# Parseltongue Imports
from parseltongue.constants import MAX_REQUEST_ATTEMPTS
from parseltongue.constants import ParseltongueProviders
from parseltongue.constants import ParseltongueReportMetrics
from parseltongue.exceptions import ParseltongueException
from parseltongue.exceptions import ParseltongueNetworkError
from parseltongue.targeting import Custom
from parseltongue.tree_builder import TreeBuilder
from parseltongue.utils.timeout import Timeout
from parseltongue.config import DFPConfig

# Parseltongue Imports - Adapter Imports
from parseltongue.adapters.dfp.interface import DFPInterface


class Parseltongue(object):
    """
    Base Interface Class
    """

    ProviderInterfaceMap = {
        ParseltongueProviders.google_dfp_premium: DFPInterface,
        ParseltongueProviders.google_dfp_small_business: DFPInterface,
    }
    """
    dict, mapping between ad service providers and their implementations
    NOTES:
        * This should probably be hosted elsewhere...
        * This doesn't serve much purpose right now since all we support
            is DFP...
    """

    ProviderConfigInterfaceMap = {
        ParseltongueProviders.google_dfp_premium: DFPConfig,
        ParseltongueProviders.google_dfp_small_business: DFPConfig,
    }
    """
    dict, mapping between ad service providers and their configuration
    containers
    NOTES:
        * This doesn't serve much purpose right now since all we support
            is DFP...
    """

    DEFAULT_NETWORK_TIMEOUT = 60 * 10
    """
    int: maximum amount of time in seconds we're willing to wait for
         a network call take
    """

    def __init__(self,
                 provider_name,
                 provider_config=None,
                 **kwargs):
        """
        Constructor

        Authenticates a provider client for the given domain.

        @param provider_name: any(parseltongue.constants.ParseltoungProvider)
        @param provider_config: child(parseltongue.config.ParseltongueConfig)

        """
        self.provider_name = provider_name
        provider_interface_class = self.get_ad_service_interface_for_provider(
            self.provider_name
        )

        # Load the provider configuration
        if provider_config:
            self.provider_config = provider_config
        else:
            _provider_config_class = \
                self.get_ad_service_config_interface_for_provider(
                    self.provider_name
                )
            self.provider_config = _provider_config_class(**kwargs)

        self.provider = provider_interface_class(self.provider_config)
        self.tree_builder = TreeBuilder(
            self.provider_name,
            self.provider,
        )

        # Attempt to access the network to check proper configuration
        try:
            self.get_network_timezone()
        except Exception as e:
            raise ParseltongueException("Provider not configured correctly. {}".format(str(e)))

    def __str__(self):
        """
        Human readable representation of this object

        @return: str
        """

        return (
            "{class_name}("
                "provider={provider},"
                "provider_config={provider_config}"
            ")"
        ).format(
            class_name=self.__class__.__name__,
            provider=self.provider,
            provider_config=self.provider_config,
        )

    @classmethod
    def get_ad_service_interface_for_provider(cls, provider_name):
        """
        Staticmethod, returns the interface class for a given ad service
        provider name

        @param provider_name: str, one of enum
            parseltongue.constants.ParseltongueProviders
        @return: descendant of
            parseltongue.adapters.abstract_interface.AbstractInterface
        """
        client_interface = cls.ProviderInterfaceMap.get(provider_name)
        if not client_interface:
            raise ValueError(
                "There is no interface defined for provider: %s" %
                provider_name
            )
        return client_interface

    @classmethod
    def get_ad_service_config_interface_for_provider(cls, provider_name):
        """
        Staticmethod, returns the config interface for a given ad
        service provider name

        @param provider_name: str, one of enum
            parseltongue.constants.ParseltongueProviders
        @return: child(parseltongue.config.ParseltongueConfig)
        """
        config_interface = cls.ProviderConfigInterfaceMap.get(provider_name)
        if not config_interface:
            raise ValueError(
                "There is no config interface defined for provider: %s" %
                provider_name
            )
        return config_interface

    def get_network_timezone(self):
        """
        Get the DFP network timezone for
        the host this client is connected to

        @return: pytz.timezone
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            return self.provider.get_network_timezone()

    def get_advertisers(self):
        """
        Queries dfp for all advertisers within their account

        @return: list(dict), returns a list of company dictionaries
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            return self.provider.get_advertisers()

    def get_campaign(self, campaign_id, include_line_items=False):
        """
        Return a campaign object given an id

        @param campaign_id: str, id of the campaign to return
        @param include_line_items: bool, include line item data as well
        @return: parseltongue.delivery.Campaign
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            campaign = self.provider.get_campaign(campaign_id)

        if include_line_items:
            campaign.line_items = self.get_campaign_line_items(campaign)

        return campaign

    def get_campaigns(self, **kwargs):
        """
        Get campaigns on optional filters

        @param order: str, PQL key to sort on (default=ID)
        @param limit: int, number of PQL results to return
        @param offset: int, page in a stream of PQL results to return
        @param filter_kwargs: dict, keyword arguments on which to filter
            PQL results
        @return: L{parseltongue.delivery.Campaign}
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            return self.provider.get_campaigns(**kwargs)

    def get_line_item(self, line_item_id):
        """
        Return a line item object given an id

        @param line_item_id: str, id of the LineItem to return
        @return: parseltongue.delivery.LineItem
        """
        attempt = 1
        response = None
        while not response and attempt <= MAX_REQUEST_ATTEMPTS:
            try:
                with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
                    response = self.provider.get_line_item(line_item_id)
            except ParseltongueNetworkError:
                logging.exception("Got network error on attempt %s" % attempt)
                attempt += 1

        if not response:
            raise ParseltongueException(
                'Could not fetch a line item in {0} attempts'.format(
                    MAX_REQUEST_ATTEMPTS
                )
            )

        return response

    def get_line_items(self, **kwargs):
        """
        Get line items on optional filters

        @param order: str, PQL key to sort on (default=ID)
        @param limit: int, number of PQL results to return
        @param offset: int, page in a stream of PQL results to return
        @param filter_kwargs: dict, keyword arguments on which to filter
            PQL results
        @return: L{parseltongue.delivery.LineItem}
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            return self.provider.get_line_items(**kwargs)

    def get_campaign_line_items(self, campaign):
        """
        Get line items on optional filters

        @param campaign: Campaign|str,
        @return: L{parseltongue.delivery.LineItem}
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            return self.provider.get_campaign_line_items(campaign)

    def get_line_item_available_inventory(self,
                                          line_item,
                                          use_start=False,
                                          preserve_id=False):
        """
        Get number of impressions available for line item.
        NOTE: The following fields are required within a line item to
        perform an availability check:
            type, cost_type, end, targeting.inventory

        @param line_item: LineItem
        @param use_start: bool, if False, checks availability from right
            now
        @param preserve_id: bool, communicate the id of the line item
            being forecasted to DFP. This is used in the case where we
            want to get a forecast on a line item in flight. This way, a
            domain doesn't need to have enough spare inventory to
            accommodate the two line items simultaneously. NOTE: If this
            is true then use_start is necessarily true.
        @return: int|None, number of available impressions
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            return self.provider.get_line_item_available_inventory(
                line_item, use_start, preserve_id
            )

    def get_creative(self, creative_id):
        """
        Return a creative object given an id

        @param creative_id: str, id of the campaign to return
        @return: parseltongue.delivery.Creative
        """
        return self.provider.get_creative(creative_id)

    def get_creatives(self, **kwargs):
        """
        Get creatives on optional filters

        @param order: str, PQL key to sort on (default=ID)
        @param limit: int, number of PQL results to return
        @param offset: int, page in a stream of PQL results to return
        @param filter_kwargs: dict, keyword arguments on which to filter
            PQL results
        @return: L{parseltongue.delivery.Creative}
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            return self.provider.get_creatives(**kwargs)

    def get_line_item_creatives(self, line_item):
        """
        Return the creatives associated with a given line item

        @param line_item: str|int|parseltongue.delivery.LineItem,
            either the id of the lineitem or an object with the id
        @return: list(parseltongue.delivery.Creative)
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            return self.provider.get_line_item_creatives(line_item)

    def get_line_item_report(self,
                             start,
                             end,
                             columns=[ParseltongueReportMetrics.ad_impressions]):
        """
        Get the number of impressions served by DFP
        for all line items between the two datetimes.

        Note: These datetimes are assumed to be in the timezone
        of the host and will be aligned to day

        Note: This API has a strange behavior where the date
        inputs only allow for a calendar day.
        This means start=1/1, end=1/1 will query against
        the entire day of 1/1

        @param start: datetime,
        @param end: datetime,
        @param columns: list(str), list of columns to include
        @return: list(dict)
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            return self.provider.get_line_item_report(
                start, end, columns,
            )

    def get_custom_target_by_name(self, name, parent_name):
        """
        Get a custom target by its name

        @param name: name of custom target
        @param parent_name: name of parent target
        @return: Custom|None
        """

        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            targets = self.provider.get_custom_targets(
                key_name=parent_name, value_name=name,
            )

        if targets and len(targets) > 1:
            raise ParseltongueException('Given name is not unique')
        elif targets:
            return targets[0]
        else:
            return None

    def construct_tree(self, target_type):
        """
        Get all data of type target_type from ad provider,
        and build a tree

        @param taget_type: parseltongueTargetTypes
        @return: NodeTree
        """
        return self.tree_builder.construct_tree(target_type)

    def update_line_item(self, line_item):
        """
        Update a Line Item for a provider

        @param line_item: parseltongue.delivery.LineItem
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            self.update_line_items([line_item])

    def update_line_items(self, line_items):
        """
        Update multiple Line Item for a provider

        @param line_items: L{parseltongue.delivery.LineItem}
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            self.provider.update_line_items(line_items)

    def create_custom_target(self, key, value):
        """
        Add a custom target to this domain's ad service provider

        @param key: parseltongue.targeting.Custom
        @param value: parseltongue.targeting.Custom
        @return: list(parseltongue.targeting.Custom)
        """
        with Timeout(self.DEFAULT_NETWORK_TIMEOUT):
            return self.provider.create_custom_target(key, value)
