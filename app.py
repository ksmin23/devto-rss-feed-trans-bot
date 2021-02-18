#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
# vim: tabstop=2 shiftwidth=2 softtabstop=2 expandtab
import os

from aws_cdk import core
from devto_rss_feed_trans_bot.devto_rss_feed_trans_bot_stack import DevtoRssFeedTransBotStack


app = core.App()
DevtoRssFeedTransBotStack(app, "DevtoRssFeedTransBot", env=core.Environment(
  account=os.environ["CDK_DEFAULT_ACCOUNT"],
  region=os.environ["CDK_DEFAULT_REGION"]))

app.synth()
