#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
# vim: tabstop=2 shiftwidth=2 softtabstop=2 expandtab

import sys
from datetime import datetime
import time
import collections
import logging
import os
import hashlib

import boto3
from bs4 import BeautifulSoup
import feedparser
from pynamodb.models import Model
from pynamodb.attributes import (
  UnicodeAttribute,
  NumberAttribute
)

LOGGER = logging.getLogger()
if len(LOGGER.handlers) > 0:
  # The Lambda environment pre-configures a handler logging to stderr.
  # If a handler is already configured, `.basicConfig` does not execute.
  # Thus we set the level directly.
  LOGGER.setLevel(logging.INFO)
else:
  logging.basicConfig(level=logging.INFO)

AWS_REGION = os.getenv('REGION_NAME', 'us-east-1')
DYNAMODB_TABLE_NAME = os.getenv('DYNAMODB_TABLE_NAME', 'AWSBuildersPost')
TRANS_SRC_LANG = os.getenv('TRANS_SRC_LANG', 'en')
TRANS_DEST_LANG = os.getenv('TRANS_DEST_LANG', 'ko')

RSS_FEED_URL = os.getenv('RSS_FEED_URL', 'https://dev.to/feed/aws-builders')

TRANS_CLIENT = None

class BlogPost(Model):
  class Meta:
    table_name = DYNAMODB_TABLE_NAME
    region = AWS_REGION

  post_id = UnicodeAttribute(hash_key=True, attr_name='id')
  title = UnicodeAttribute()
  author = UnicodeAttribute()
  summary_short = UnicodeAttribute()
  summary_short_translated = UnicodeAttribute()
  src_lang_code = UnicodeAttribute()
  dest_lang_code = UnicodeAttribute()
  link = UnicodeAttribute()
  tags = UnicodeAttribute(null=True)
  p_time = NumberAttribute(default=0)
  createdAt = UnicodeAttribute()
  updatedAt = UnicodeAttribute()


def get_feeds_translated(feed_ids):
  feeds_translated = {}
  for item in BlogPost.batch_get(feed_ids):
    feeds_translated[item.post_id] = item.createdAt
  return feeds_translated


def save_feed_translated(feed_entries):
  if not feed_entries:
    return

  with BlogPost.batch_write() as batch:
    items = [BlogPost(**elem) for elem in feed_entries]
    for item in items:
      batch.save(item)


def get_summary(html, limit=2):
  soup = BeautifulSoup(html, features='html.parser')
  paragraphs = soup.find_all('p')
  return ' '.join(e.text for e in paragraphs[:limit])


def parse_feed(feed_url):
  parsed_rss_feed = feedparser.parse(feed_url)

  status = parsed_rss_feed['status']
  if 200 != status:
    return {}

  ENTRY_KEYS = '''author,link,title'''.split(',')
  entry_list = []
  for entry in parsed_rss_feed['entries']:
    doc = {k: entry[k] for k in ENTRY_KEYS}
    doc['post_id'] = hashlib.md5(doc['link'].encode('utf-8')).hexdigest()
    doc['p_time'] = int(datetime(*entry['published_parsed'][:6]).timestamp())
    tags = ','.join([e['term'] for e in entry.get('tags', []) if e])
    if tags:
      doc['tags'] = tags
    doc['summary_short'] = get_summary(entry['summary'])

    doc['createdAt'] = datetime.utcnow().isoformat(timespec='milliseconds') + "Z"
    doc['updatedAt'] = doc['createdAt']
    entry_list.append(doc)
  return {'entries': entry_list, 'count': len(entry_list)}


def get_or_create_translator(region_name):
  global TRANS_CLIENT

  if not TRANS_CLIENT:
    TRANS_CLIENT = boto3.client('translate', region_name=region_name)
  assert TRANS_CLIENT
  return TRANS_CLIENT


def translate(trans_client, text, src='auto', dest='ko'):
  res = trans_client.translate_text(Text=text,
    SourceLanguageCode=src, TargetLanguageCode=dest)

  if 200 == res['ResponseMetadata']['HTTPStatusCode']:
    return {'text': res['TranslatedText'], 'src': src, 'dest': dest}
  else:
    return {}


def lambda_handler(event, context):
  LOGGER.info('start to get rss feed')

  feeds_parsed = parse_feed(RSS_FEED_URL)
  #feeds_parsed := {'entries': [post_id, author, link, title, p_time, tags, summary_short, createdAt, updatedAt], 'count': 'num of entries' }

  feed_ids = [e['post_id'] for e in feeds_parsed['entries']]
  feeds_translated = get_feeds_translated(feed_ids)

  new_feed_entries = [elem for elem in feeds_parsed['entries'] if elem['post_id'] not in feeds_translated]
  new_feeds_parsed = {'entries': new_feed_entries, 'count': len(new_feed_entries)}
  LOGGER.info('new_rss_feed: count={count}'.format(count=new_feeds_parsed['count']))
  if new_feeds_parsed['count'] == 0:
    LOGGER.info('end')
    return

  translator = get_or_create_translator(region_name=AWS_REGION)
  for elem in new_feeds_parsed['entries']:
    translated_res = translate(translator, elem['summary_short'],
      src=TRANS_SRC_LANG, dest=TRANS_DEST_LANG)
    elem.update(summary_short_translated = translated_res['text'],
      src_lang_code = translated_res['src'],
      dest_lang_code = translated_res['dest'])
  LOGGER.info('add translated rss feed')

  #feeds_parsed := {'entries': [post_id, author, link, title, p_time, tags, summary_short, createdAt, updatedAt, summary_short_translated, src_lang_code, dest_lang_code], 'count': 'num of entries' }
  save_feed_translated(new_feeds_parsed['entries'])
  LOGGER.info('save translated rss feeds in DynamoDB')
  LOGGER.info('end')


if __name__ == '__main__':
  event = {
    "id": "cdc73f9d-aea9-11e3-9d5a-835b769c0d9c",
    "detail-type": "Scheduled Event",
    "source": "aws.events",
    "account": "",
    "time": "1970-01-01T00:00:00Z",
    "region": "us-east-1",
    "resources": [
      "arn:aws:events:us-east-1:123456789012:rule/ExampleRule"
    ],
    "detail": {}
  }
  event['time'] = datetime.utcnow().strftime('%Y-%m-%dT%H:00:00')

  start_t = time.time()
  lambda_handler(event, {})
  end_t = time.time()
  LOGGER.info('run_time: {:.2f}'.format(end_t - start_t))
