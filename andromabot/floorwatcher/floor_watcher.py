import asyncio
from datetime import datetime
import logging
from typing import List

import discord
from discord.activity import ActivityType

from andromabot.time_utils import relative_time

from ..config.config import CollectionConfig
from ..stargaze import fetch_trait_asks
from .floor_flow import FloorFlow

LOG = logging.getLogger(__name__)


def get_min_ask(trait_asks: dict):
    def asking_price(x):
        return x["ask"].price.amount

    min_ask = None
    for trait,values in trait_asks.items():
        for value,asks in values.items():
            for ask in asks:
                if min_ask is None or asking_price(ask) < asking_price(min_ask):
                    min_ask = ask
    return min_ask

class FloorWatcher:
    def __init__(self, client: discord.Client, collections: List[CollectionConfig]):
        self.client = client
        self.collections = collections
        self.latest_asks = {}
        self.floors = {}
        self.floor_updates: dict[str,datetime] = {}

        for c in self.collections:
            self.floors[c.name] = [0, 0, 0, 0, 0]

        list_collections_cmd = discord.app_commands.Command(
            name="listcollections",
            description="List tracked Stargaze collections with their floor price",
            callback=self.list_collections,
        )
        self.client.tree.add_command(list_collections_cmd)

        query_floor_cmd = discord.app_commands.Command(
            name="querytraitfloor",
            description="Query the floor pricing for a specific trait",
            callback=self.query_trait_floor,
        )
        self.client.tree.add_command(query_floor_cmd)

    async def begin_watching(self):
        self.bg_tasks = []
        for collection in self.collections:
            task = self.client.loop.create_task(self.track_floor_pricing(collection))
            self.bg_tasks.append(task)

    async def update_asks(self, collection: CollectionConfig):
        name = collection.name
        activity = discord.Activity(type=ActivityType.watching, name="the stars 🌌🔭")
        await self.client.change_presence(activity=activity)

        LOG.info(f"Updating asks for '{name}'")
        trait_asks = fetch_trait_asks(name, collection.strict_validation)
        collection_floor = get_min_ask(trait_asks)

        if collection.enable_trait_query:
            self.latest_asks[name] = trait_asks
        new_floor = collection_floor["ask"].price.get_stars()
        self.floors[name].insert(0, new_floor)
        self.floors[name].pop()
        self.floor_updates[name] = datetime.utcnow()
        LOG.info(f"Finished updating asks for '{name}'")

        await self.client.change_presence(activity=None)

    async def track_floor_pricing(self, collection: CollectionConfig):
        interval = collection.refresh_interval

        while True:
            try:
                await self.update_asks(collection)
            except Exception as e:
                LOG.warning(f"Exception during update_asks: {e}")

            LOG.info(f"Refreshing {collection.name} in {interval} seconds")
            await asyncio.sleep(interval)

    async def list_collections(self, interaction: discord.Interaction):
        """List the currently tracked collections."""
        message = "**Tracked collections**\n"
        for collection, floor in self.floors.items():
            td = datetime.utcnow() - self.floor_updates[collection]
            message += f"- {collection}: ({floor[0]:,} $STARS updated {relative_time(td)})\n"
        await interaction.response.send_message(message)

    async def query_trait_floor(
        self,
        interaction: discord.Interaction,
    ):
        floor_flow = FloorFlow(self.latest_asks)
        await floor_flow.start(interaction)
