# cogs_dbmanage.py

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("bot.dbmanage")

DETECTED_BY_OPTIONS = [
    app_commands.Choice(name="TASE",          value="TASE"),
    app_commands.Choice(name="ROTECTOR",      value="ROTECTOR"),
    app_commands.Choice(name="MOCO-CO",       value="MOCO-CO"),
    app_commands.Choice(name="FLAGCHECKER",   value="FLAGCHECKER"),
    app_commands.Choice(name="ROBLOXWATCHER", value="ROBLOXWATCHER"),
    app_commands.Choice(name="BLOXYCLEANER",  value="BLOXYCLEANER"),
    app_commands.Choice(name="SELFBOT",       value="SELFBOT"),
]


async def _is_admin(bot, user) -> bool:
    if await bot.is_owner(user): return True
    return bot.storage.has_role("developers", user.id)


class DBManageCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    # ─────────────────────────────────────────────
    # /dbmanage add
    # ─────────────────────────────────────────────

    @app_commands.command(name="dbmanage", description="Manually add or remove a user from the database.")
    @app_commands.describe(
        action      = "Add or remove a user from the database.",
        user_id     = "Discord user ID to add or remove.",
        server      = "Server name they were detected in.",
        still_in    = "Are they currently in the server? Yes = seen_users. No = previous_users.",
        detected_by = "Which source detected this user.",
        evidence    = "Evidence link (Discord CDN or other attachment URL).",
        note        = "Optional note about this entry.",
    )
    @app_commands.choices(detected_by=DETECTED_BY_OPTIONS)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def dbmanage(
        self,
        interaction: discord.Interaction,
        action:      app_commands.Choice[str],
        user_id:     str,
        server:      Optional[str]                  = None,
        still_in:    Optional[bool]                 = None,
        detected_by: Optional[app_commands.Choice[str]] = None,
        evidence:    Optional[str]                  = None,
        note:        Optional[str]                  = None,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not await _is_admin(self.bot, interaction.user):
            return await interaction.followup.send("No permission.", ephemeral=True)

        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.followup.send("Invalid user ID.", ephemeral=True)

        # Fetch Discord user for username
        username = f"ID:{uid}"
        try:
            user = await self.bot.fetch_user(uid)
            username = str(user)
        except Exception:
            pass

        if action.value == "add":
            await self._handle_add(
                interaction = interaction,
                uid         = uid,
                username    = username,
                server      = server or "Unknown",
                still_in    = still_in if still_in is not None else True,
                detected_by = detected_by.value if detected_by else "FLAGCHECKER",
                evidence    = evidence,
                note        = note,
            )
        elif action.value == "remove":
            await self._handle_remove(
                interaction = interaction,
                uid         = uid,
                username    = username,
                server      = server,
            )

    async def _handle_add(self, interaction, uid: int, username: str,
                          server: str, still_in: bool, detected_by: str,
                          evidence: Optional[str], note: Optional[str]):
        storage = self.bot.storage

        if still_in:
            # ── Add to seen_users (currently in server) ──
            try:
                for col in storage.all_cols:
                    col.update_one(
                        {"user_id": uid, "guild_name": server},
                        {
                            "$set": {
                                "username":        username,
                                "guild_name":      server,
                                "still_in_server": True,
                                "detected_by":     detected_by,
                                "evidence":        evidence or "",
                                "note":            note or "",
                                "last_seen":       datetime.now(timezone.utc),
                                "manually_added":  True,
                            },
                            "$setOnInsert": {
                                "user_id":    uid,
                                "guild_id":   0,
                                "join_date":  "unknown",
                                "first_seen": datetime.now(timezone.utc),
                            }
                        },
                        upsert=True
                    )
                    break  # only write to active DB

                # Also add to flagged_users
                storage.add_flagged_user(
                    user_id  = str(uid),
                    username = username,
                    sources  = [detected_by],
                    servers  = [{"name": server, "sources": [detected_by]}],
                )

                embed = discord.Embed(
                    title       = "✅ Added to seen_users",
                    description = (
                        f"**User:** `{uid}` ({username})\n"
                        f"**Server:** {server}\n"
                        f"**Status:** Currently in server\n"
                        f"**Detected By:** {detected_by}\n"
                        f"**Evidence:** {evidence or 'None'}\n"
                        f"**Note:** {note or 'None'}"
                    ),
                    color = 0x57F287,
                )
                embed.set_footer(text=f"Added by {interaction.user} • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
                await interaction.followup.send(embed=embed, ephemeral=True)

            except Exception as e:
                log.error("[DBManage] add seen_users error: %s", e)
                await interaction.followup.send(f"Error adding to seen_users: {e}", ephemeral=True)

        else:
            # ── Add to previous_users (left the server) ──
            try:
                for col in storage.all_cols:
                    col.database["previous_users"].update_one(
                        {"user_id": uid, "guild_name": server},
                        {
                            "$set": {
                                "username":        username,
                                "guild_name":      server,
                                "still_in_server": False,
                                "detected_by":     detected_by,
                                "evidence":        evidence or "",
                                "note":            note or "",
                                "left_at":         datetime.now(timezone.utc),
                                "manually_added":  True,
                            },
                            "$setOnInsert": {
                                "user_id":    uid,
                                "guild_id":   0,
                                "join_date":  "unknown",
                                "first_seen": datetime.now(timezone.utc),
                            }
                        },
                        upsert=True
                    )
                    break

                # Also add to flagged_users
                storage.add_flagged_user(
                    user_id  = str(uid),
                    username = username,
                    sources  = [detected_by],
                    servers  = [{"name": f"(Previous Server) {server}", "sources": [detected_by]}],
                )

                embed = discord.Embed(
                    title       = "✅ Added to previous_users",
                    description = (
                        f"**User:** `{uid}` ({username})\n"
                        f"**Server:** {server}\n"
                        f"**Status:** Previously in server\n"
                        f"**Detected By:** {detected_by}\n"
                        f"**Evidence:** {evidence or 'None'}\n"
                        f"**Note:** {note or 'None'}"
                    ),
                    color = 0x5865F2,
                )
                embed.set_footer(text=f"Added by {interaction.user} • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
                await interaction.followup.send(embed=embed, ephemeral=True)

            except Exception as e:
                log.error("[DBManage] add previous_users error: %s", e)
                await interaction.followup.send(f"Error adding to previous_users: {e}", ephemeral=True)

    async def _handle_remove(self, interaction, uid: int, username: str, server: Optional[str]):
        storage  = self.bot.storage
        removed  = []
        errors   = []

        for db in storage._all_member_dbs:
            try:
                # Remove from seen_users
                query = {"user_id": uid}
                if server:
                    query["guild_name"] = server
                result = db["seen_users"].delete_many(query)
                if result.deleted_count:
                    removed.append(f"seen_users: {result.deleted_count} record(s)")
            except Exception as e:
                errors.append(f"seen_users: {e}")

            try:
                # Remove from previous_users
                query = {"user_id": uid}
                if server:
                    query["guild_name"] = server
                result = db["previous_users"].delete_many(query)
                if result.deleted_count:
                    removed.append(f"previous_users: {result.deleted_count} record(s)")
            except Exception as e:
                errors.append(f"previous_users: {e}")

            try:
                # Remove from flagged_users
                result = db["flagged_users"].delete_one({"user_id": str(uid)})
                if result.deleted_count:
                    removed.append(f"flagged_users: {result.deleted_count} record(s)")
            except Exception as e:
                errors.append(f"flagged_users: {e}")

        if removed:
            embed = discord.Embed(
                title       = "✅ Removed from database",
                description = (
                    f"**User:** `{uid}` ({username})\n"
                    f"**Server filter:** {server or 'All servers'}\n\n"
                    f"**Removed from:**\n" + "\n".join(f"• {r}" for r in removed)
                ),
                color = 0xED4245,
            )
        else:
            embed = discord.Embed(
                title       = "⚠️ Nothing removed",
                description = f"**User:** `{uid}` ({username})\nNo records found{' for server: ' + server if server else ''}.",
                color       = 0xFEE75C,
            )

        if errors:
            embed.add_field(name="Errors", value="\n".join(f"• {e}" for e in errors), inline=False)

        embed.set_footer(text=f"Removed by {interaction.user} • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────
    # /violationadd
    # ─────────────────────────────────────────────

    @app_commands.command(name="violationadd", description="Manually add a violation to a user.")
    @app_commands.describe(
        user_id     = "Discord user ID.",
        server      = "Server name the violation occurred in.",
        detected_by = "Source that detected the violation.",
        evidence    = "Evidence link (Discord CDN or attachment URL).",
        note        = "Optional note about this violation.",
        still_in    = "Is the user currently in the server?",
    )
    @app_commands.choices(detected_by=DETECTED_BY_OPTIONS)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def violationadd(
        self,
        interaction: discord.Interaction,
        user_id:     str,
        server:      str,
        detected_by: app_commands.Choice[str],
        still_in:    bool                       = True,
        evidence:    Optional[str]              = None,
        note:        Optional[str]              = None,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not await _is_admin(self.bot, interaction.user):
            return await interaction.followup.send("No permission.", ephemeral=True)

        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.followup.send("Invalid user ID.", ephemeral=True)

        username = f"ID:{uid}"
        try:
            user     = await self.bot.fetch_user(uid)
            username = str(user)
        except Exception:
            pass

        try:
            storage = self.bot.storage

            violation = {
                "server":      server,
                "detected_by": detected_by.value,
                "evidence":    evidence or "",
                "note":        note or "",
                "still_in":    still_in,
                "added_by":    str(interaction.user),
                "added_at":    datetime.now(timezone.utc).isoformat(),
            }

            # Add to flagged_users violations array
            storage._active_db["flagged_users"].update_one(
                {"user_id": str(uid)},
                {
                    "$push": {"violations": violation},
                    "$addToSet": {
                        "sources_flagged": detected_by.value,
                        "servers":         {"name": server if still_in else f"(Previous Server) {server}",
                                           "source": detected_by.value}
                    },
                    "$set": {
                        "username":   username,
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$setOnInsert": {
                        "user_id":    str(uid),
                        "flagged_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True
            )

            # Also add to seen_users or previous_users
            if still_in:
                for col in storage.all_cols:
                    col.update_one(
                        {"user_id": uid, "guild_name": server},
                        {
                            "$set": {
                                "username":        username,
                                "guild_name":      server,
                                "still_in_server": True,
                                "detected_by":     detected_by.value,
                                "evidence":        evidence or "",
                                "note":            note or "",
                                "last_seen":       datetime.now(timezone.utc),
                                "manually_added":  True,
                            },
                            "$setOnInsert": {
                                "user_id":    uid,
                                "guild_id":   0,
                                "join_date":  "unknown",
                                "first_seen": datetime.now(timezone.utc),
                            }
                        },
                        upsert=True
                    )
                    break
            else:
                storage._active_db["previous_users"].update_one(
                    {"user_id": uid, "guild_name": server},
                    {
                        "$set": {
                            "username":        username,
                            "guild_name":      server,
                            "still_in_server": False,
                            "detected_by":     detected_by.value,
                            "evidence":        evidence or "",
                            "note":            note or "",
                            "left_at":         datetime.now(timezone.utc),
                            "manually_added":  True,
                        },
                        "$setOnInsert": {
                            "user_id":    uid,
                            "guild_id":   0,
                            "join_date":  "unknown",
                            "first_seen": datetime.now(timezone.utc),
                        }
                    },
                    upsert=True
                )

            embed = discord.Embed(
                title       = "✅ Violation Added",
                description = (
                    f"**User:** `{uid}` ({username})\n"
                    f"**Server:** {server}\n"
                    f"**Status:** {'Currently in server' if still_in else 'Previously in server'}\n"
                    f"**Detected By:** {detected_by.value}\n"
                    f"**Evidence:** {evidence or 'None'}\n"
                    f"**Note:** {note or 'None'}"
                ),
                color = 0x57F287,
            )
            embed.set_footer(text=f"Added by {interaction.user} • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            log.error("[ViolationAdd] error: %s", e)
            await interaction.followup.send(f"Error adding violation: {e}", ephemeral=True)

    # ─────────────────────────────────────────────
    # /violationremove
    # ─────────────────────────────────────────────

    @app_commands.command(name="violationremove", description="Remove a violation from a user.")
    @app_commands.describe(
        user_id = "Discord user ID.",
        server  = "Server name to remove violation for. Leave empty to remove all.",
        note    = "Reason for removing this violation.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def violationremove(
        self,
        interaction: discord.Interaction,
        user_id:     str,
        server:      Optional[str] = None,
        note:        Optional[str] = None,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not await _is_admin(self.bot, interaction.user):
            return await interaction.followup.send("No permission.", ephemeral=True)

        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.followup.send("Invalid user ID.", ephemeral=True)

        username = f"ID:{uid}"
        try:
            user     = await self.bot.fetch_user(uid)
            username = str(user)
        except Exception:
            pass

        try:
            storage = self.bot.storage
            removed = []

            for db in storage._all_member_dbs:
                doc = db["flagged_users"].find_one({"user_id": str(uid)})
                if not doc:
                    continue

                if server:
                    # Remove specific server violation
                    result = db["flagged_users"].update_one(
                        {"user_id": str(uid)},
                        {
                            "$pull": {
                                "violations": {"server": server},
                                "servers":    {"name": {"$in": [server, f"(Previous Server) {server}"]}}
                            },
                            "$set": {"updated_at": datetime.now(timezone.utc)}
                        }
                    )
                    if result.modified_count:
                        removed.append(f"Removed violation for server: **{server}**")
                else:
                    # Remove all violations
                    result = db["flagged_users"].update_one(
                        {"user_id": str(uid)},
                        {
                            "$set": {
                                "violations":      [],
                                "sources_flagged": [],
                                "servers":         [],
                                "updated_at":      datetime.now(timezone.utc),
                            }
                        }
                    )
                    if result.modified_count:
                        removed.append("Removed all violations")

            if removed:
                embed = discord.Embed(
                    title       = "✅ Violation Removed",
                    description = (
                        f"**User:** `{uid}` ({username})\n"
                        + "\n".join(f"• {r}" for r in removed)
                        + (f"\n**Reason:** {note}" if note else "")
                    ),
                    color = 0xED4245,
                )
            else:
                embed = discord.Embed(
                    title       = "⚠️ Nothing removed",
                    description = f"**User:** `{uid}` ({username})\nNo violations found{' for server: ' + server if server else ''}.",
                    color       = 0xFEE75C,
                )

            embed.set_footer(text=f"Removed by {interaction.user} • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            log.error("[ViolationRemove] error: %s", e)
            await interaction.followup.send(f"Error removing violation: {e}", ephemeral=True)
