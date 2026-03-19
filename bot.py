# =========================================================
# DISCORD TRADING ALERT BOT — PARTIE 1
# Base du bot + configuration + structure
# =========================================================

# --------- INSTALLATION REQUISE ---------
# Dans le terminal (une seule fois) :
# pip install discord.py python-dotenv requests pandas numpy pytz
# ---------------------------------------

import os
import asyncio
import json
from datetime import datetime

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# =========================================================
# 1. CHARGEMENT VARIABLES D'ENVIRONNEMENT
# =========================================================

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise ValueError("❌ Tu dois mettre ton DISCORD_TOKEN dans un fichier .env")

# =========================================================
# 2. CONFIGURATION GLOBALE
# =========================================================

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.guilds = True
INTENTS.members = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

NEW_YORK_TZ = "America/New_York"

# =========================================================
# 3. ACTIFS SURVEILLÉS
# =========================================================

ASSETS = {
    "NQ": {"type": "index"},
    "DOW": {"type": "index"},
    "SP500": {"type": "index"},
    "DXY": {"type": "index"},
    "EURUSD": {"type": "forex"},
    "GBPJPY": {"type": "forex"},
    "XAUUSD": {"type": "metal"},
    "BRN": {"type": "oil"},
    "BTC": {"type": "crypto"},
    "ETH": {"type": "crypto"},
}

TIMEFRAMES = ["MN", "W1", "D1", "H4"]

TIMEFRAME_COLORS = {
    "MN": 0x9b59b6,   # violet
    "W1": 0x3498db,   # bleu
    "D1": 0x2ecc71,   # vert
    "H4": 0xf39c12,   # orange
}

# =========================================================
# 4. CONFIGURATION PAR SERVEUR (AUTO-SAUVEGARDE)
# =========================================================

CONFIG_FILE = "guild_config.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


GUILD_CONFIG = load_config()


def get_guild_config(guild_id: int):
    gid = str(guild_id)
    if gid not in GUILD_CONFIG:
        GUILD_CONFIG[gid] = {
            "mode": "single",  # single | multi
            "single_channel": None,
            "asset_channels": {},
            "ping_role_id": None,
        }
        save_config(GUILD_CONFIG)
    return GUILD_CONFIG[gid]

# =========================================================
# 5. OUTILS EMBED
# =========================================================


def make_embed(title: str, description: str, color: int):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.utcnow(),
    )
    embed.set_footer(text="Trading Alert Bot")
    return embed

# =========================================================
# 6. EVENEMENTS BOT
# =========================================================


@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    print("------")

# =========================================================
# 7. COMMANDES CONFIGURATION
# =========================================================


@bot.command(name="setmode")
@commands.has_permissions(administrator=True)
async def set_mode(ctx, mode: str):
    """
    !setmode single
    !setmode multi
    """
    mode = mode.lower()
    if mode not in ["single", "multi"]:
        await ctx.send("❌ Mode invalide: single ou multi")
        return

    cfg = get_guild_config(ctx.guild.id)
    cfg["mode"] = mode
    save_config(GUILD_CONFIG)

    await ctx.send(f"✅ Mode configuré sur: **{mode}**")


@bot.command(name="setchannel")
@commands.has_permissions(administrator=True)
async def set_channel(ctx, channel: discord.TextChannel):
    """
    !setchannel #salon-alertes
    """
    cfg = get_guild_config(ctx.guild.id)
    cfg["single_channel"] = channel.id
    save_config(GUILD_CONFIG)

    await ctx.send(f"✅ Salon principal défini: {channel.mention}")


@bot.command(name="setassetchannel")
@commands.has_permissions(administrator=True)
async def set_asset_channel(ctx, asset: str, channel: discord.TextChannel):
    """
    !setassetchannel BTC #btc-alerts
    """
    asset = asset.upper()
    if asset not in ASSETS:
        await ctx.send("❌ Actif inconnu")
        return

    cfg = get_guild_config(ctx.guild.id)
    cfg["asset_channels"][asset] = channel.id
    save_config(GUILD_CONFIG)

    await ctx.send(f"✅ Salon pour {asset}: {channel.mention}")


@bot.command(name="setrole")
@commands.has_permissions(administrator=True)
async def set_role(ctx, role: discord.Role):
    """
    !setrole @traders
    """
    cfg = get_guild_config(ctx.guild.id)
    cfg["ping_role_id"] = role.id
    save_config(GUILD_CONFIG)

    await ctx.send(f"✅ Rôle ping configuré: {role.mention}")

# =========================================================
# 8. FONCTION ENVOI MESSAGE CONFIGURÉ
# =========================================================


async def send_configured_alert(guild: discord.Guild, asset: str, embed: discord.Embed):
    cfg = get_guild_config(guild.id)

    role_mention = ""
    if cfg.get("ping_role_id"):
        role = guild.get_role(cfg["ping_role_id"])
        if role:
            role_mention = role.mention

    # Mode salon unique
    if cfg.get("mode") == "single":
        channel_id = cfg.get("single_channel")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel:
            await channel.send(content=role_mention, embed=embed)

    # Mode multi salons
    else:
        channel_id = cfg.get("asset_channels", {}).get(asset)
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel:
            await channel.send(content=role_mention, embed=embed)

# =========================================================
# 9. LANCEMENT BOT
# =========================================================

if __name__ == "__main__":
    bot.run(TOKEN)
# =========================================================
# DISCORD TRADING ALERT BOT — PARTIE 2
# Connexion aux données de marché + prix temps réel
# =========================================================

# Cette partie ajoute :
# - Récupération des données OHLC
# - Support Crypto (Binance)
# - Support autres actifs (via Yahoo Finance)
# - Multi-timeframes (MN / W1 / D1 / H4)

# 👉 AJOUTE ces imports en haut du fichier principal si absents

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# =========================================================
# 1. MAPPINGS SYMBOLS API
# =========================================================

BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
}

YF_SYMBOLS = {
    "NQ": "NQ=F",
    "DOW": "YM=F",
    "SP500": "ES=F",
    "DXY": "DX-Y.NYB",
    "EURUSD": "EURUSD=X",
    "GBPJPY": "GBPJPY=X",
    "XAUUSD": "GC=F",
    "BRN": "BZ=F",
}

# =========================================================
# 2. TIMEFRAMES → API INTERVALS
# =========================================================

BINANCE_INTERVALS = {
    "MN": "1M",
    "W1": "1w",
    "D1": "1d",
    "H4": "4h",
}

YF_INTERVALS = {
    "MN": "1mo",
    "W1": "1wk",
    "D1": "1d",
    "H4": "1h",  # approx (Yahoo ne fournit pas 4h natif)
}

# =========================================================
# 3. UTILITAIRE — ARRONDIR HEURE H4
# =========================================================

def resample_to_h4(df: pd.DataFrame):
    df = df.copy()
    df.index = pd.to_datetime(df.index)

    ohlc = df.resample("4H").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()

    return ohlc

# =========================================================
# 4. BINANCE DATA (CRYPTO)
# =========================================================


def get_binance_klines(symbol: str, interval: str, limit=500):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    df = pd.DataFrame(data, columns=[
        "open_time","Open","High","Low","Close","Volume",
        "close_time","qav","trades","tbbav","tbqav","ignore"
    ])

    df["Open"] = df["Open"].astype(float)
    df["High"] = df["High"].astype(float)
    df["Low"] = df["Low"].astype(float)
    df["Close"] = df["Close"].astype(float)
    df["Volume"] = df["Volume"].astype(float)

    df["time"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("time", inplace=True)

    return df[["Open","High","Low","Close","Volume"]]

# =========================================================
# 5. YAHOO FINANCE DATA (AUTRES ACTIFS)
# =========================================================


def get_yahoo_data(symbol: str, interval: str, lookback_days=365):
    end = datetime.utcnow()
    start = end - timedelta(days=lookback_days)

    url = "https://query1.finance.yahoo.com/v8/finance/chart/{}".format(symbol)
    params = {
        "period1": int(start.timestamp()),
        "period2": int(end.timestamp()),
        "interval": interval,
    }

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    j = r.json()

    result = j["chart"]["result"][0]
    timestamps = result["timestamp"]
    quotes = result["indicators"]["quote"][0]

    df = pd.DataFrame({
        "time": pd.to_datetime(timestamps, unit="s"),
        "Open": quotes["open"],
        "High": quotes["high"],
        "Low": quotes["low"],
        "Close": quotes["close"],
        "Volume": quotes.get("volume", [0]*len(timestamps)),
    }).dropna()

    df.set_index("time", inplace=True)

    if interval == "1h":
        df = resample_to_h4(df)

    return df

# =========================================================
# 6. ROUTEUR PRINCIPAL DATA
# =========================================================


def get_ohlc(asset: str, timeframe: str) -> pd.DataFrame | None:
    try:
        # Crypto → Binance
        if asset in BINANCE_SYMBOLS:
            symbol = BINANCE_SYMBOLS[asset]
            interval = BINANCE_INTERVALS[timeframe]
            return get_binance_klines(symbol, interval)

        # Autres → Yahoo
        if asset in YF_SYMBOLS:
            symbol = YF_SYMBOLS[asset]
            interval = YF_INTERVALS[timeframe]
            return get_yahoo_data(symbol, interval)

    except Exception as e:
        print(f"Erreur data {asset} {timeframe}: {e}")
        return None

    return None

# =========================================================
# 7. PRIX ACTUEL SIMPLE
# =========================================================


def get_current_price(asset: str) -> float | None:
    try:
        # Crypto rapide
        if asset in BINANCE_SYMBOLS:
            url = "https://api.binance.com/api/v3/ticker/price"
            r = requests.get(url, params={"symbol": BINANCE_SYMBOLS[asset]}, timeout=10)
            r.raise_for_status()
            return float(r.json()["price"])

        # Autres via dernière close
        df = get_ohlc(asset, "H4")
        if df is not None and len(df):
            return float(df["Close"].iloc[-1])

    except Exception as e:
        print(f"Erreur prix {asset}: {e}")
        return None

    return None
# =========================================================
# DISCORD TRADING ALERT BOT — PARTIE 3
# Détection Swing Points + Cassures + Niveaux Institutionnels
# =========================================================

# Cette partie ajoute :
# - Détection swing high / swing low (méthode classique)
# - Détection prise de liquidité (mèche)
# - Détection cassure confirmée (clôture)
# - Détection niveaux institutionnels adaptatifs

# =========================================================
# 1. PARAMÈTRES SWING
# =========================================================

SWING_LEFT = 2
SWING_RIGHT = 2

# Mémoire des derniers swings détectés
LAST_SWINGS = {}  # { asset: { tf: {"high": float, "low": float} } }

# =========================================================
# 2. DÉTECTION SWING POINTS
# =========================================================


def detect_swings(df):
    highs = df["High"].values
    lows = df["Low"].values

    swing_highs = []
    swing_lows = []

    for i in range(SWING_LEFT, len(df) - SWING_RIGHT):
        high = highs[i]
        low = lows[i]

        left_highs = highs[i - SWING_LEFT:i]
        right_highs = highs[i + 1:i + 1 + SWING_RIGHT]

        left_lows = lows[i - SWING_LEFT:i]
        right_lows = lows[i + 1:i + 1 + SWING_RIGHT]

        if high > max(left_highs) and high > max(right_highs):
            swing_highs.append((df.index[i], high))

        if low < min(left_lows) and low < min(right_lows):
            swing_lows.append((df.index[i], low))

    return swing_highs, swing_lows

# =========================================================
# 3. DERNIERS SWINGS VALIDES
# =========================================================


def get_last_valid_swings(asset, timeframe, df):
    swing_highs, swing_lows = detect_swings(df)

    if not swing_highs or not swing_lows:
        return None, None

    last_high = swing_highs[-1][1]
    last_low = swing_lows[-1][1]

    LAST_SWINGS.setdefault(asset, {})[timeframe] = {
        "high": float(last_high),
        "low": float(last_low),
    }

    return last_high, last_low

# =========================================================
# 4. TYPES DE CASSURES
# =========================================================


def detect_breaks(current_price, last_high, last_low, last_close):
    events = []

    # Prise liquidité haute (mèche)
    if current_price > last_high and last_close <= last_high:
        events.append("liquidity_high")

    # Prise liquidité basse
    if current_price < last_low and last_close >= last_low:
        events.append("liquidity_low")

    # Cassure confirmée haute
    if last_close > last_high:
        events.append("break_high")

    # Cassure confirmée basse
    if last_close < last_low:
        events.append("break_low")

    return events

# =========================================================
# 5. NIVEAUX INSTITUTIONNELS ADAPTATIFS
# =========================================================


def institutional_step(price: float) -> float:
    if price >= 100000:
        return 10000
    if price >= 10000:
        return 1000
    if price >= 1000:
        return 100
    if price >= 100:
        return 10
    if price >= 10:
        return 1
    if price >= 1:
        return 0.1
    return 0.01


LAST_INSTITUTIONAL_ALERT = {}  # {asset: level}


def check_institutional_level(asset: str, price: float):
    step = institutional_step(price)
    level = round(price / step) * step

    # Distance max autorisée (proche du niveau)
    tolerance = step * 0.02

    if abs(price - level) <= tolerance:
        last = LAST_INSTITUTIONAL_ALERT.get(asset)
        if last != level:
            LAST_INSTITUTIONAL_ALERT[asset] = level
            return level

    return None

# =========================================================
# 6. FORMATAGE MESSAGES
# =========================================================


def tf_label(tf):
    return f"**__{tf}__**"


def format_price(p):
    if p >= 1000:
        return f"{p:,.2f}"
    return f"{p:.5f}"
# =========================================================
# DISCORD TRADING ALERT BOT — PARTIE 4
# Moteur d'analyse automatique + Alertes Discord
# =========================================================

# Cette partie ajoute :
# - Boucle d’analyse continue
# - Analyse multi-actifs
# - Analyse multi-timeframes
# - Détection événements trading
# - Envoi alertes Discord configurées

from discord.ext import tasks

# =========================================================
# 1. FRÉQUENCE D’ANALYSE
# =========================================================

ANALYSIS_INTERVAL_SECONDS = 60  # vérifie chaque minute

# =========================================================
# 2. MÉMOIRE ANTI-SPAM ALERTES
# =========================================================

ALERT_MEMORY = set()  # évite doublons


def alert_key(asset, tf, event):
    return f"{asset}-{tf}-{event}"

# =========================================================
# 3. CRÉATION EMBEDS ALERTES
# =========================================================


def build_break_embed(asset, tf, event, price, level):
    color = TIMEFRAME_COLORS.get(tf, 0xffffff)

    if event == "liquidity_high":
        title = f"💧 Prise de liquidité HAUTE — {asset}"
        desc = (
            f"Timeframe : {tf_label(tf)}\n"
            f"Prix actuel : {format_price(price)}\n"
            f"Swing High : {format_price(level)}"
        )

    elif event == "liquidity_low":
        title = f"💧 Prise de liquidité BASSE — {asset}"
        desc = (
            f"Timeframe : {tf_label(tf)}\n"
            f"Prix actuel : {format_price(price)}\n"
            f"Swing Low : {format_price(level)}"
        )

    elif event == "break_high":
        title = f"🚀 CASSURE CONFIRMÉE HAUSSIÈRE — {asset}"
        desc = (
            f"Timeframe : {tf_label(tf)}\n"
            f"Clôture : {format_price(price)}\n"
            f"Ancien Swing High : {format_price(level)}"
        )

    elif event == "break_low":
        title = f"📉 CASSURE CONFIRMÉE BAISSIÈRE — {asset}"
        desc = (
            f"Timeframe : {tf_label(tf)}\n"
            f"Clôture : {format_price(price)}\n"
            f"Ancien Swing Low : {format_price(level)}"
        )

    else:
        return None

    return make_embed(title, desc, color)



def build_institutional_embed(asset, price, level):
    title = f"🏦 Niveau Institutionnel — {asset}"
    desc = (
        f"Prix actuel : {format_price(price)}\n"
        f"Niveau clé : {format_price(level)}"
    )
    return make_embed(title, desc, 0xe74c3c)

# =========================================================
# 4. ANALYSE D’UN ACTIF
# =========================================================


async def analyze_asset(asset: str):
    price = get_current_price(asset)
    if price is None:
        return

    # Niveaux institutionnels
    inst_level = check_institutional_level(asset, price)
    if inst_level is not None:
        embed = build_institutional_embed(asset, price, inst_level)
        for guild in bot.guilds:
            await send_configured_alert(guild, asset, embed)

    # Analyse swings multi-timeframes
    for tf in TIMEFRAMES:
        df = get_ohlc(asset, tf)
        if df is None or len(df) < 10:
            continue

        last_high, last_low = get_last_valid_swings(asset, tf, df)
        if last_high is None:
            continue

        last_close = float(df["Close"].iloc[-1])
        events = detect_breaks(price, last_high, last_low, last_close)

        for event in events:
            key = alert_key(asset, tf, event)
            if key in ALERT_MEMORY:
                continue

            ALERT_MEMORY.add(key)

            level = last_high if "high" in event else last_low
            embed = build_break_embed(asset, tf, event, price, level)
            if embed is None:
                continue

            for guild in bot.guilds:
                await send_configured_alert(guild, asset, embed)

# =========================================================
# 5. BOUCLE PRINCIPALE
# =========================================================


@tasks.loop(seconds=ANALYSIS_INTERVAL_SECONDS)
async def market_loop():
    for asset in ASSETS.keys():
        try:
            await analyze_asset(asset)
            await asyncio.sleep(1)  # évite spam API
        except Exception as e:
            print(f"Erreur analyse {asset}: {e}")


@market_loop.before_loop
async def before_market_loop():
    await bot.wait_until_ready()
    print("📊 Moteur d’analyse démarré")


# =========================================================
# 6. DÉMARRAGE AUTO DE LA BOUCLE
# =========================================================


@bot.event
async def on_ready():
    if not market_loop.is_running():
        market_loop.start()
    print(f"✅ Bot prêt : {bot.user}")
# =========================================================
# DISCORD TRADING ALERT BOT — PARTIE 5
# News économiques automatiques (Investing style)
# =========================================================

# Cette partie ajoute :
# - Récupération calendrier économique du jour
# - Filtre impact fort (3 étoiles)
# - Corrélation devises / actifs surveillés
# - Message AVANT publication (heure + prévision)
# - Mise à jour APRÈS publication (résultat)
# - Fuseau horaire New York

# ⚠️ NOTE : Investing.com n'a pas d'API publique officielle
# On utilise une API économique alternative gratuite

import pytz
from datetime import datetime

# =========================================================
# 1. CONFIG
# =========================================================

NY_TZ = pytz.timezone("America/New_York")
NEWS_CHECK_INTERVAL = 60  # secondes

# Devises liées aux actifs surveillés
RELEVANT_CURRENCIES = {
    "USD", "EUR", "GBP", "JPY"
}

# Mémoire
NEWS_MEMORY = {}         # id -> data
NEWS_MESSAGES = {}       # id -> discord.Message

# =========================================================
# 2. API NEWS (TradingEconomics - démo)
# =========================================================

# 🔹 Crée un compte gratuit : https://tradingeconomics.com/
# 🔹 Récupère ta clé API
TE_API_KEY = "033d8680560849a:ejaao2he96lx6g9"


def fetch_today_news():
    try:
        today = datetime.now(NY_TZ).strftime("%Y-%m-%d")
        url = f"https://api.tradingeconomics.com/calendar?c={TE_API_KEY}&d1={today}&d2={today}"

        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        events = []
        for item in data:
            # Impact fort uniquement
            if item.get("Importance") != 3:
                continue

            currency = item.get("Currency")
            if currency not in RELEVANT_CURRENCIES:
                continue

            events.append({
                "id": item.get("CalendarId"),
                "title": item.get("Event"),
                "currency": currency,
                "time": item.get("Date"),
                "forecast": item.get("Forecast"),
                "previous": item.get("Previous"),
                "actual": item.get("Actual"),
            })

        return events

    except Exception as e:
        print(f"Erreur news: {e}")
        return []

# =========================================================
# 3. FORMATAGE
# =========================================================


def parse_event_time(timestr):
    dt = datetime.fromisoformat(timestr.replace("Z", "+00:00"))
    return dt.astimezone(NY_TZ)


def news_embed_preview(event):
    t = parse_event_time(event["time"])
    title = f"📰 News Éco Importante — {event['currency']}"
    desc = (
        f"**{event['title']}**\n\n"
        f"Heure (NY) : {t.strftime('%H:%M')}\n"
        f"Prévision : {event['forecast']}\n"
        f"Précédent : {event['previous']}"
    )
    return make_embed(title, desc, 0x3498db)


def news_embed_result(event):
    t = parse_event_time(event["time"])
    title = f"📰 Résultat News — {event['currency']}"
    desc = (
        f"**{event['title']}**\n\n"
        f"Heure (NY) : {t.strftime('%H:%M')}\n"
        f"Prévision : {event['forecast']}\n"
        f"Résultat : **{event['actual']}**\n"
        f"Précédent : {event['previous']}"
    )
    return make_embed(title, desc, 0x2ecc71)

# =========================================================
# 4. ENVOI CONFIGURÉ NEWS
# =========================================================


async def send_news_to_all_guilds(embed):
    for guild in bot.guilds:
        # envoie dans salon principal si défini
        cfg = get_guild_config(guild.id)
        channel_id = cfg.get("single_channel")
        if not channel_id:
            continue
        channel = guild.get_channel(channel_id)
        if channel:
            msg = await channel.send(embed=embed)
            return msg
    return None

# =========================================================
# 5. BOUCLE NEWS
# =========================================================


@tasks.loop(seconds=NEWS_CHECK_INTERVAL)
async def news_loop():
    events = fetch_today_news()

    for ev in events:
        eid = str(ev["id"])

        # Nouveau — message preview
        if eid not in NEWS_MEMORY:
            NEWS_MEMORY[eid] = ev
            embed = news_embed_preview(ev)
            msg = await send_news_to_all_guilds(embed)
            if msg:
                NEWS_MESSAGES[eid] = msg

        # Résultat publié — update message
        elif ev.get("actual") and eid in NEWS_MESSAGES:
            embed = news_embed_result(ev)
            try:
                await NEWS_MESSAGES[eid].edit(embed=embed)
            except:
                pass


@news_loop.before_loop
async def before_news_loop():
    await bot.wait_until_ready()
    print("📰 News loop démarrée")

# =========================================================
# 6. AUTO START
# =========================================================


@bot.event
async def on_ready():
    if not news_loop.is_running():
        news_loop.start()
    print("📰 Module news actif")
