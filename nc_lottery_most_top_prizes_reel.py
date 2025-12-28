"""
NC Lottery "Most Top Prizes" Reel Generator
============================================

This script generates Instagram Reel content highlighting games with
the MOST TOP PRIZES remaining ($5K+ top prizes only).

Features:
- Blue to purple gradient background
- Money tree watermark
- Countdown format (3, 2, 1) with #1 pick blurred
- Rankings based on # of top prizes left (differential as tiebreaker)
- Manual run only (not scheduled)

Output is deployed to GitHub Pages for easy access.
"""

import requests
from bs4 import BeautifulSoup
import re
import time
from typing import List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import sys
import io

# Try to import moviepy components
try:
    from moviepy.editor import ImageClip, concatenate_videoclips
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    print("Warning: moviepy not available, video generation will be skipped")


# Constants
REEL_WIDTH = 1080
REEL_HEIGHT = 1920
GAME_IMAGE_WIDTH = 850
MIN_TOP_PRIZE = 5000  # Only consider games with top prize >= $5000


def get_eastern_time():
    """Get current time in Eastern timezone"""
    utc_now = datetime.now(timezone.utc)
    eastern = utc_now - timedelta(hours=5)
    return eastern


@dataclass
class PrizeTier:
    """Represents a single prize tier"""
    value: float
    total: int
    remaining: int
    
    @property
    def percent_remaining(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.remaining / self.total) * 100


@dataclass
class GameData:
    """Data structure for a scratch-off game"""
    game_number: str
    game_name: str
    ticket_price: float
    url: str
    image_url: str = ""
    status: str = ""
    prize_tiers: List[PrizeTier] = field(default_factory=list)
    
    def get_top_prize(self) -> Optional[PrizeTier]:
        if not self.prize_tiers:
            return None
        return max(self.prize_tiers, key=lambda x: x.value)
    
    def get_bottom_prize(self) -> Optional[PrizeTier]:
        if not self.prize_tiers:
            return None
        return min(self.prize_tiers, key=lambda x: x.value)
    
    def calculate_differential(self) -> Tuple[float, float, float]:
        top = self.get_top_prize()
        bottom = self.get_bottom_prize()
        
        if not top or not bottom:
            return 0.0, 0.0, 0.0
        
        top_pct = top.percent_remaining
        bottom_pct = bottom.percent_remaining
        differential = top_pct - bottom_pct
        
        return bottom_pct, top_pct, differential


class NCLotteryAnalyzer:
    """Analyzes NC Lottery scratch-off games"""
    
    BASE_URL = "https://nclottery.com"
    PRIZES_URL = f"{BASE_URL}/scratch-off-prizes-remaining"
    GAMES_ENDING_URL = f"{BASE_URL}/scratch-off-games-ending"
    
    def __init__(self, delay_seconds: float = 0.5, verbose: bool = True):
        self.delay = delay_seconds
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        self.games_in_claims = set()
    
    def log(self, message: str):
        if self.verbose:
            print(message)
    
    def fetch_page(self, url: str) -> Optional[str]:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                self.log(f"  Attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(self.delay * 2)
        return None
    
    def fetch_image(self, url: str) -> Optional[Image.Image]:
        """Fetch an image from URL and return as PIL Image"""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return Image.open(io.BytesIO(response.content))
        except Exception as e:
            self.log(f"  Failed to fetch image: {e}")
            return None
    
    def parse_prize_value(self, prize_str: str) -> float:
        cleaned = prize_str.replace('$', '').replace(',', '').strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    
    def parse_number(self, num_str: str) -> int:
        cleaned = num_str.replace(',', '').strip()
        try:
            return int(cleaned)
        except ValueError:
            return 0
    
    def get_games_in_claims_period(self) -> set:
        self.log("Checking for games in claims period...")
        html = self.fetch_page(self.GAMES_ENDING_URL)
        if not html:
            return set()
        
        soup = BeautifulSoup(html, 'html.parser')
        claims_games = set()
        today = datetime.now()
        
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 5:
                    try:
                        game_num = cells[0].get_text(strip=True)
                        end_date_str = cells[3].get_text(strip=True)
                        claim_date_str = cells[4].get_text(strip=True)
                        
                        try:
                            end_date = datetime.strptime(end_date_str, '%b %d, %Y')
                            claim_date = datetime.strptime(claim_date_str, '%b %d, %Y')
                            
                            if end_date < today <= claim_date:
                                claims_games.add(game_num)
                        except ValueError:
                            pass
                    except (IndexError, AttributeError):
                        continue
        
        return claims_games
    
    def get_game_details_from_page(self, game_url: str) -> Tuple[float, str]:
        """Get ticket price and image URL from game page"""
        time.sleep(self.delay)
        
        html = self.fetch_page(game_url)
        if not html:
            return 0.0, ""
        
        soup = BeautifulSoup(html, 'html.parser')
        page_text = soup.get_text()
        
        # Get price
        price = 0.0
        price_match = re.search(r'Ticket\s*Price\s*\$(\d+)', page_text, re.IGNORECASE)
        if price_match:
            price = float(price_match.group(1))
        else:
            for element in soup.find_all(['div', 'span', 'p', 'td']):
                text = element.get_text(strip=True)
                if 'Ticket Price' in text:
                    price_match = re.search(r'\$(\d+)', text)
                    if price_match:
                        price = float(price_match.group(1))
                        break
        
        # Get game image URL
        image_url = ""
        img_tags = soup.find_all('img')
        for img in img_tags:
            src = img.get('src', '')
            alt = img.get('alt', '').lower()
            if 'scratch' in src.lower() or 'game' in alt or 'ticket' in alt:
                if src.startswith('/'):
                    image_url = self.BASE_URL + src
                elif src.startswith('http'):
                    image_url = src
                break
        
        if not image_url:
            for img in img_tags:
                src = img.get('src', '')
                if '/scratch-off/' in src or 'game' in src.lower():
                    if src.startswith('/'):
                        image_url = self.BASE_URL + src
                    elif src.startswith('http'):
                        image_url = src
                    break
        
        return price, image_url
    
    def parse_game_section(self, game_table) -> Optional[GameData]:
        try:
            rows = game_table.find_all('tr')
            if len(rows) < 2:
                return None
            
            header_row = rows[0]
            game_link = header_row.find('a', href=re.compile(r'/scratch-off/\d+/'))
            if not game_link:
                return None
            
            href = game_link['href']
            game_name = game_link.get_text(strip=True)
            
            game_num_match = re.search(r'/scratch-off/(\d+)/', href)
            if not game_num_match:
                return None
            game_number = game_num_match.group(1)
            
            header_text = header_row.get_text()
            num_in_text = re.search(r'Game\s*Number:\s*(\d+)', header_text)
            if num_in_text:
                game_number = num_in_text.group(1)
            
            status = "Reordered" if "Reordered" in header_text else ""
            game_url = self.BASE_URL + href
            
            prize_tiers = []
            for row in rows[1:]:
                cells = row.find_all('td')
                if len(cells) >= 4:
                    try:
                        value_text = cells[0].get_text(strip=True)
                        if not value_text.startswith('$'):
                            continue
                        
                        prize_value = self.parse_prize_value(value_text)
                        if prize_value <= 0:
                            continue
                        
                        total = self.parse_number(cells[2].get_text(strip=True))
                        remaining = self.parse_number(cells[3].get_text(strip=True))
                        
                        if total > 0:
                            prize_tiers.append(PrizeTier(
                                value=prize_value,
                                total=total,
                                remaining=remaining
                            ))
                    except (IndexError, ValueError):
                        continue
            
            if not prize_tiers:
                return None
            
            return GameData(
                game_number=game_number,
                game_name=game_name,
                ticket_price=0.0,
                url=game_url,
                status=status,
                prize_tiers=prize_tiers
            )
            
        except Exception as e:
            return None
    
    def scrape_active_games(self) -> List[GameData]:
        self.games_in_claims = self.get_games_in_claims_period()
        
        self.log("\nFetching prizes remaining page...")
        html = self.fetch_page(self.PRIZES_URL)
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        games = []
        all_tables = soup.find_all('table')
        
        self.log(f"Found {len(all_tables)} tables to analyze...")
        
        processed_games = set()
        
        for table in all_tables:
            game_link = table.find('a', href=re.compile(r'/scratch-off/\d+/'))
            if not game_link:
                continue
            
            href = game_link['href']
            game_num_match = re.search(r'/scratch-off/(\d+)/', href)
            if not game_num_match:
                continue
            
            game_number = game_num_match.group(1)
            
            if game_number in processed_games:
                continue
            
            if game_number in self.games_in_claims:
                self.log(f"Skipping Game #{game_number} - in claims period")
                processed_games.add(game_number)
                continue
            
            game_data = self.parse_game_section(table)
            
            if game_data:
                processed_games.add(game_number)
                self.log(f"Processing Game #{game_data.game_number}: {game_data.game_name}")
                
                price, image_url = self.get_game_details_from_page(game_data.url)
                game_data.ticket_price = price
                game_data.image_url = image_url
                
                if game_data.ticket_price > 0:
                    self.log(f"  Price: ${game_data.ticket_price:.0f}, Image: {'Found' if image_url else 'Not found'}")
                    games.append(game_data)
        
        return games
    
    def analyze_and_rank_by_top_prizes(self) -> List[Tuple[GameData, float, float, float]]:
        """Analyze games and rank by most top prizes remaining ($5K+ only)"""
        games = self.scrape_active_games()
        
        if not games:
            return []
        
        self.log(f"\nProcessed {len(games)} active games")
        
        results = []
        for game in games:
            top_prize = game.get_top_prize()
            # Only include games with top prize >= $5000
            if top_prize and top_prize.value >= MIN_TOP_PRIZE:
                bottom_pct, top_pct, differential = game.calculate_differential()
                results.append((game, bottom_pct, top_pct, differential))
        
        self.log(f"Found {len(results)} games with top prize >= ${MIN_TOP_PRIZE:,}")
        
        # Sort by top prizes remaining (desc), then differential (desc) as tiebreaker
        results.sort(key=lambda x: (x[0].get_top_prize().remaining, x[3]), reverse=True)
        return results


class ReelGenerator:
    """Generates Instagram Reel video and standalone images for Most Top Prizes"""
    
    def __init__(self, analyzer: NCLotteryAnalyzer):
        self.analyzer = analyzer
        self.width = REEL_WIDTH
        self.height = REEL_HEIGHT
        self.fonts = self._load_fonts()
        
    def _load_fonts(self) -> dict:
        """Load fonts with fallbacks"""
        fonts = {}
        
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]
        
        bold_font_path = None
        regular_font_path = None
        
        for path in font_paths:
            if os.path.exists(path):
                if 'Bold' in path or 'bd' in path:
                    bold_font_path = path
                else:
                    regular_font_path = path
        
        if not bold_font_path:
            bold_font_path = regular_font_path
        if not regular_font_path:
            regular_font_path = bold_font_path
            
        try:
            fonts['title'] = ImageFont.truetype(bold_font_path, 82) if bold_font_path else ImageFont.load_default()
            fonts['subtitle'] = ImageFont.truetype(bold_font_path, 48) if bold_font_path else ImageFont.load_default()
            fonts['rank'] = ImageFont.truetype(bold_font_path, 70) if bold_font_path else ImageFont.load_default()
            fonts['info'] = ImageFont.truetype(bold_font_path, 52) if bold_font_path else ImageFont.load_default()
            fonts['disclaimer'] = ImageFont.truetype(bold_font_path, 36) if bold_font_path else ImageFont.load_default()
            fonts['cta'] = ImageFont.truetype(bold_font_path, 52) if bold_font_path else ImageFont.load_default()
            fonts['date'] = ImageFont.truetype(bold_font_path, 56) if bold_font_path else ImageFont.load_default()
            fonts['small'] = ImageFont.truetype(regular_font_path, 38) if regular_font_path else ImageFont.load_default()
            fonts['prizes_left'] = ImageFont.truetype(bold_font_path, 64) if bold_font_path else ImageFont.load_default()
        except Exception as e:
            print(f"Font loading error: {e}, using defaults")
            default = ImageFont.load_default()
            fonts = {k: default for k in ['title', 'subtitle', 'rank', 'info', 'disclaimer', 'cta', 'date', 'small', 'prizes_left']}
        
        return fonts
    
    def _create_gradient_background(self) -> Image.Image:
        """Create a blue to purple gradient background with money tree watermark"""
        img = Image.new('RGB', (self.width, self.height))
        draw = ImageDraw.Draw(img)
        
        # Blue to Purple gradient
        start_color = (74, 144, 217)   # Blue
        end_color = (139, 92, 246)     # Purple
        
        for y in range(self.height):
            ratio = y / self.height
            r = int(start_color[0] + (end_color[0] - start_color[0]) * ratio)
            g = int(start_color[1] + (end_color[1] - start_color[1]) * ratio)
            b = int(start_color[2] + (end_color[2] - start_color[2]) * ratio)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
        
        # Add money tree watermark
        self._add_money_tree_watermark(img)
        
        return img
    
    def _add_money_tree_watermark(self, img: Image.Image):
        """Add a subtle money tree silhouette watermark"""
        draw = ImageDraw.Draw(img, 'RGBA')
        
        trunk_color = (255, 255, 255, 25)
        trunk_x = self.width - 180
        trunk_bottom = self.height - 100
        
        draw.polygon([
            (trunk_x - 15, trunk_bottom),
            (trunk_x + 15, trunk_bottom),
            (trunk_x + 10, trunk_bottom - 200),
            (trunk_x - 10, trunk_bottom - 200)
        ], fill=trunk_color)
        
        leaf_color = (255, 255, 255, 20)
        centers = [
            (trunk_x, trunk_bottom - 280),
            (trunk_x - 60, trunk_bottom - 220),
            (trunk_x + 60, trunk_bottom - 220),
            (trunk_x - 40, trunk_bottom - 320),
            (trunk_x + 40, trunk_bottom - 320),
            (trunk_x, trunk_bottom - 380),
        ]
        
        for cx, cy in centers:
            radius = 70
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=leaf_color)
        
        dollar_color = (255, 215, 0, 30)
        try:
            dollar_font = self.fonts.get('small', ImageFont.load_default())
            dollar_positions = [
                (trunk_x - 50, trunk_bottom - 350),
                (trunk_x + 30, trunk_bottom - 280),
                (trunk_x - 30, trunk_bottom - 250),
                (trunk_x + 50, trunk_bottom - 320),
            ]
            for dx, dy in dollar_positions:
                draw.text((dx, dy), "$", font=dollar_font, fill=dollar_color)
        except:
            pass
    
    def _draw_rounded_rect(self, draw: ImageDraw, x1: int, y1: int, x2: int, y2: int, 
                            radius: int, fill: Tuple):
        """Draw a rounded rectangle (compatible with older Pillow versions)"""
        draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
        draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
        draw.ellipse([x1, y1, x1 + radius * 2, y1 + radius * 2], fill=fill)
        draw.ellipse([x2 - radius * 2, y1, x2, y1 + radius * 2], fill=fill)
        draw.ellipse([x1, y2 - radius * 2, x1 + radius * 2, y2], fill=fill)
        draw.ellipse([x2 - radius * 2, y2 - radius * 2, x2, y2], fill=fill)
    
    def _add_text_with_glow(self, draw: ImageDraw, position: Tuple[int, int], 
                            text: str, font: ImageFont, fill: str = "white",
                            glow_color: Tuple[int, int, int] = (0, 0, 0),
                            glow_radius: int = 4):
        """Add text with glow effect for better readability"""
        x, y = position
        
        for offset_x in range(-glow_radius, glow_radius + 1):
            for offset_y in range(-glow_radius, glow_radius + 1):
                if offset_x != 0 or offset_y != 0:
                    draw.text((x + offset_x, y + offset_y), text, font=font, 
                              fill=(*glow_color, 100), anchor="mm")
        
        draw.text(position, text, font=font, fill=fill, anchor="mm")
    
    def _center_text_glow(self, draw: ImageDraw, y: int, text: str, font: ImageFont, 
                          fill: str = "white", glow_color: Tuple[int, int, int] = (0, 0, 0)):
        """Draw centered text with glow at given y position"""
        x = self.width // 2
        self._add_text_with_glow(draw, (x, y), text, font, fill, glow_color)
    
    def create_title_slide(self, date_str: str) -> Image.Image:
        """Create the title/intro slide for Most Top Prizes"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img, 'RGBA')
        
        base_y = 380
        
        # Title
        self._center_text_glow(draw, base_y, "NC LOTTERY", self.fonts['title'], fill="#FFFFFF")
        self._center_text_glow(draw, base_y + 90, "SCRATCH OFF", self.fonts['title'], fill="#FFFFFF")
        
        # "MOST TOP PRIZES"
        self._center_text_glow(draw, base_y + 220, "* * * MOST TOP PRIZES * * *", self.fonts['rank'], fill="#FFD700")
        self._center_text_glow(draw, base_y + 300, "REMAINING", self.fonts['rank'], fill="#FFD700")
        
        # $5K+ qualifier - prominent
        self._center_text_glow(draw, base_y + 390, "( $5,000+ TOP PRIZES ONLY )", self.fonts['subtitle'], fill="#00FFFF")
        
        self._center_text_glow(draw, base_y + 470, date_str, self.fonts['date'], fill="#FFFFFF")
        
        # Explanation
        self._center_text_glow(draw, base_y + 580, "Ranked by # of top prizes", self.fonts['subtitle'], fill="#E0E0FF")
        self._center_text_glow(draw, base_y + 640, "still available to win", self.fonts['subtitle'], fill="#E0E0FF")
        
        # Disclaimer box
        disclaimer_y = base_y + 760
        self._draw_rounded_rect(draw, 120, disclaimer_y - 30, self.width - 120, disclaimer_y + 100, 20, (0, 0, 0, 180))
        self._center_text_glow(draw, disclaimer_y + 10, "! Not financial advice !", self.fonts['disclaimer'], fill="#FFD700")
        self._center_text_glow(draw, disclaimer_y + 55, "Play responsibly", self.fonts['disclaimer'], fill="#FFFFFF")
        
        return img
    
    def create_multi_game_slide(self, games: List[Tuple[GameData, float, float, float]], 
                                  start_rank: int, slide_label: str) -> Image.Image:
        """Create a slide showing 3 games condensed"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img, 'RGBA')
        
        # Header
        header_y = 120
        self._center_text_glow(draw, header_y, slide_label, self.fonts['rank'], fill="#FFD700")
        
        # Calculate positions for 3 games vertically
        game_height = 520
        start_y = 220
        
        for i, (game, bottom_pct, top_pct, diff) in enumerate(games):
            game_y = start_y + (i * game_height)
            rank = start_rank + i
            
            top_prize = game.get_top_prize()
            prizes_left_text = f"{top_prize.remaining} of {top_prize.total} LEFT"
            
            # Dark card background for each game
            card_top = game_y
            card_bottom = game_y + game_height - 30
            self._draw_rounded_rect(draw, 50, card_top, self.width - 50, card_bottom, 20, (0, 0, 0, 150))
            
            # Rank badge on left
            badge_x = 100
            badge_y = card_top + 60
            self._draw_rounded_rect(draw, badge_x - 40, badge_y - 35, badge_x + 40, badge_y + 35, 10, (255, 215, 0, 255))
            draw.text((badge_x, badge_y), f"#{rank}", font=self.fonts['subtitle'], fill=(0, 0, 0), anchor="mm")
            
            # Try to fetch game image
            game_img = None
            if game.image_url:
                game_img = self.analyzer.fetch_image(game.image_url)
            
            # Game image (smaller, on the left side)
            img_x = 180
            img_y = card_top + 100
            img_width = 280
            
            if game_img:
                if game_img.mode != 'RGB':
                    game_img = game_img.convert('RGB')
                
                img_aspect = game_img.width / game_img.height
                target_width = img_width
                target_height = int(target_width / img_aspect)
                
                max_height = 350
                if target_height > max_height:
                    target_height = max_height
                    target_width = int(target_height * img_aspect)
                
                try:
                    game_img = game_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                except AttributeError:
                    game_img = game_img.resize((target_width, target_height), Image.LANCZOS)
                
                # White border
                border = 6
                framed = Image.new('RGB', (target_width + border*2, target_height + border*2), 'white')
                framed.paste(game_img, (border, border))
                
                img.paste(framed, (img_x, img_y))
                
                info_x = img_x + target_width + border*2 + 40
            else:
                info_x = img_x + 50
            
            # Refresh draw after paste
            draw = ImageDraw.Draw(img, 'RGBA')
            
            # Game info on the right
            info_y = card_top + 120
            
            # Prizes remaining - prominent
            self._add_text_with_glow(draw, (info_x + 200, info_y), prizes_left_text, 
                                     self.fonts['subtitle'], fill="#00FFFF")
            
            # Game name (truncate if too long)
            game_name = game.game_name
            if len(game_name) > 18:
                game_name = game_name[:16] + "..."
            self._add_text_with_glow(draw, (info_x + 200, info_y + 70), game_name, 
                                     self.fonts['disclaimer'], fill="#FFFFFF")
            
            def format_prize(value):
                if value >= 1000000:
                    return f"${value/1000000:.1f}M"
                elif value >= 1000:
                    return f"${value/1000:.0f}K"
                return f"${value:.0f}"
            
            # Price and top prize value
            details = f"${int(game.ticket_price)} | Top: {format_prize(top_prize.value)}"
            self._add_text_with_glow(draw, (info_x + 200, info_y + 140), details, 
                                     self.fonts['small'], fill="#FFD700")
            
            # Differential
            diff_color = "#00FF88" if diff > 0 else "#FF6B6B"
            self._add_text_with_glow(draw, (info_x + 200, info_y + 200), f"Diff: {diff:+.1f}%", 
                                     self.fonts['small'], fill=diff_color)
        
        return img
    
    def create_cta_slide(self) -> Image.Image:
        """Create the call-to-action slide"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img, 'RGBA')
        
        center_y = self.height // 2 - 50
        
        self._center_text_glow(draw, center_y - 80, "FULL RANKINGS", self.fonts['title'], fill="#FFFFFF")
        self._center_text_glow(draw, center_y + 10, "+ DAILY UPDATES", self.fonts['rank'], fill="#00FFFF")
        
        self._center_text_glow(draw, center_y + 140, "Link in bio", self.fonts['cta'], fill="#FFD700")
        
        box_top = center_y + 220
        self._draw_rounded_rect(draw, 100, box_top, self.width - 100, box_top + 220, 20, (255, 255, 255, 240))
        
        draw.text((self.width // 2, box_top + 50), "Which game are", font=self.fonts['cta'], 
                  fill=(50, 50, 80), anchor="mm")
        draw.text((self.width // 2, box_top + 110), "you trying?", font=self.fonts['cta'], 
                  fill=(50, 50, 80), anchor="mm")
        draw.text((self.width // 2, box_top + 175), "Comment below!", font=self.fonts['small'], 
                  fill=(100, 100, 140), anchor="mm")
        
        return img
    
    def generate_all_content(self, results: List[Tuple[GameData, float, float, float]], 
                             output_dir: str = "."):
        """Generate all slides and video - 9 games across 3 slides (3 per slide)"""
        
        # Get top 9 games (already sorted by most top prizes remaining)
        top_games = results[:9]
        
        eastern_now = get_eastern_time()
        date_str = eastern_now.strftime('%B %d, %Y')
        
        slides = []
        slide_durations = []
        
        print(f"\nGenerating 'Most Top Prizes' slides for {date_str}...")
        
        # Slide 1: Title
        print("  Creating title slide...")
        title_slide = self.create_title_slide(date_str)
        title_slide.save(os.path.join(output_dir, "mtp-slide-1-title.png"))
        slides.append(title_slide)
        slide_durations.append(5)
        
        # Slides 2-4: Games 1-9 (3 per slide)
        slide_labels = ["#1 - #3", "#4 - #6", "#7 - #9"]
        for slide_idx in range(3):
            start_idx = slide_idx * 3
            end_idx = start_idx + 3
            games_for_slide = top_games[start_idx:end_idx]
            
            if not games_for_slide:
                break
                
            start_rank = start_idx + 1
            label = slide_labels[slide_idx]
            
            print(f"  Creating slide for games {label}...")
            slide = self.create_multi_game_slide(games_for_slide, start_rank, label)
            slide.save(os.path.join(output_dir, f"mtp-slide-{slide_idx + 2}-games-{start_rank}-{start_rank + 2}.png"))
            slides.append(slide)
            slide_durations.append(6)  # Slightly longer for 3 games
        
        # Final Slide: CTA
        print("  Creating CTA slide...")
        cta_slide = self.create_cta_slide()
        cta_slide.save(os.path.join(output_dir, "mtp-slide-5-cta.png"))
        slides.append(cta_slide)
        slide_durations.append(4)
        
        print(f"\n* Generated {len(slides)} standalone images")
        
        # Generate video if moviepy is available
        if MOVIEPY_AVAILABLE:
            print("\nGenerating video...")
            success = self._create_video(slides, slide_durations, output_dir)
            if not success:
                print("! Video generation failed, but images are available")
        else:
            print("\n! Video generation skipped (moviepy not available)")
        
        return slides
    
    def _create_video(self, slides: List[Image.Image], durations: List[int], 
                      output_dir: str):
        """Create the video"""
        
        try:
            import numpy as np
            from moviepy.editor import ImageClip, concatenate_videoclips
            
            clips = []
            
            for i, (slide, duration) in enumerate(zip(slides, durations)):
                slide_rgb = slide.convert('RGB')
                slide_array = np.array(slide_rgb)
                
                clip = ImageClip(slide_array).set_duration(duration)
                clips.append(clip)
                print(f"    Created clip {i+1}/{len(slides)} ({duration}s)")
            
            print("  Concatenating clips...")
            final_video = concatenate_videoclips(clips, method="compose")
            
            output_path = os.path.join(output_dir, "most-top-prizes-reel.mp4")
            print(f"  Writing video to {output_path}...")
            
            final_video.write_videofile(
                output_path,
                fps=24,
                codec='libx264',
                audio=False,
                preset='ultrafast',
                threads=2,
                logger=None
            )
            
            final_video.close()
            for clip in clips:
                clip.close()
            
            print(f"* Video saved to: {output_path}")
            return True
            
        except Exception as e:
            print(f"X Video generation failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """Main execution function"""
    print("=" * 60)
    print("NC Lottery 'Most Top Prizes' Reel Generator")
    print("=" * 60)
    
    eastern_now = get_eastern_time()
    print(f"Started at: {eastern_now.strftime('%Y-%m-%d %H:%M:%S')} Eastern")
    print()
    
    # Run analysis
    analyzer = NCLotteryAnalyzer(delay_seconds=0.5, verbose=True)
    results = analyzer.analyze_and_rank_by_top_prizes()
    
    if not results:
        print("\nERROR: No games found with top prize >= $5,000!")
        sys.exit(1)
    
    print(f"\nAnalysis complete! Found {len(results)} qualifying games.")
    
    # Show top 3
    print("\nTop 3 by Most Top Prizes Remaining:")
    for i, (game, bottom, top, diff) in enumerate(results[:3], 1):
        top_prize = game.get_top_prize()
        print(f"  #{i}: {game.game_name} - {top_prize.remaining} of {top_prize.total} left (${top_prize.value:,.0f} top prize)")
    
    # Generate reel and images
    generator = ReelGenerator(analyzer)
    generator.generate_all_content(results, output_dir=".")
    
    eastern_end = get_eastern_time()
    print(f"\nFinished at: {eastern_end.strftime('%Y-%m-%d %H:%M:%S')} Eastern")


if __name__ == "__main__":
    main()
