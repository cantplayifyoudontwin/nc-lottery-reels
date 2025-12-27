"""
NC Lottery Reel Generator - GitHub Actions Version
===================================================

This script generates a daily Instagram Reel video and standalone images
featuring the top NC Lottery scratch-off games.

Features:
- Blue to purple gradient background
- Money tree watermark
- Countdown format (3, 2, 1) with #1 pick blurred
- Eastern timezone date display
- No emoji dependencies (uses text symbols)

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
GAME_IMAGE_WIDTH = 850  # Increased from 700


def get_eastern_time():
    """Get current time in Eastern timezone"""
    utc_now = datetime.now(timezone.utc)
    # Eastern is UTC-5 (EST) or UTC-4 (EDT)
    # For simplicity, use -5 and let the display be close enough
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
    
    def analyze_and_rank_games(self) -> List[Tuple[GameData, float, float, float]]:
        games = self.scrape_active_games()
        
        if not games:
            return []
        
        self.log(f"\nProcessed {len(games)} active games")
        
        results = []
        for game in games:
            bottom_pct, top_pct, differential = game.calculate_differential()
            results.append((game, bottom_pct, top_pct, differential))
        
        results.sort(key=lambda x: x[3], reverse=True)
        return results


class ReelGenerator:
    """Generates Instagram Reel video and standalone images"""
    
    def __init__(self, analyzer: NCLotteryAnalyzer):
        self.analyzer = analyzer
        self.width = REEL_WIDTH
        self.height = REEL_HEIGHT
        self.fonts = self._load_fonts()
        self.money_tree_watermark = None
        
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
            # Larger, bolder fonts
            fonts['title'] = ImageFont.truetype(bold_font_path, 82) if bold_font_path else ImageFont.load_default()
            fonts['subtitle'] = ImageFont.truetype(bold_font_path, 48) if bold_font_path else ImageFont.load_default()
            fonts['rank'] = ImageFont.truetype(bold_font_path, 70) if bold_font_path else ImageFont.load_default()
            fonts['info'] = ImageFont.truetype(bold_font_path, 52) if bold_font_path else ImageFont.load_default()
            fonts['disclaimer'] = ImageFont.truetype(bold_font_path, 36) if bold_font_path else ImageFont.load_default()
            fonts['cta'] = ImageFont.truetype(bold_font_path, 52) if bold_font_path else ImageFont.load_default()
            fonts['date'] = ImageFont.truetype(bold_font_path, 56) if bold_font_path else ImageFont.load_default()
            fonts['small'] = ImageFont.truetype(regular_font_path, 38) if regular_font_path else ImageFont.load_default()
        except Exception as e:
            print(f"Font loading error: {e}, using defaults")
            default = ImageFont.load_default()
            fonts = {k: default for k in ['title', 'subtitle', 'rank', 'info', 'disclaimer', 'cta', 'date', 'small']}
        
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
        
        # Add money tree watermark silhouette in bottom right
        self._add_money_tree_watermark(img)
        
        return img
    
    def _add_money_tree_watermark(self, img: Image.Image):
        """Add a subtle money tree silhouette watermark"""
        draw = ImageDraw.Draw(img, 'RGBA')
        
        # Draw a simple stylized tree silhouette
        # Trunk
        trunk_color = (255, 255, 255, 25)  # Very subtle white
        trunk_x = self.width - 180
        trunk_bottom = self.height - 100
        
        # Draw trunk
        draw.polygon([
            (trunk_x - 15, trunk_bottom),
            (trunk_x + 15, trunk_bottom),
            (trunk_x + 10, trunk_bottom - 200),
            (trunk_x - 10, trunk_bottom - 200)
        ], fill=trunk_color)
        
        # Draw leaves (multiple overlapping circles for tree canopy effect)
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
        
        # Add $ symbols scattered around (money tree theme)
        dollar_color = (255, 215, 0, 30)  # Subtle gold
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
        # Draw rectangle without corners
        draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
        draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
        # Draw four corners
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
        
        # Draw glow (multiple offset shadows)
        for offset_x in range(-glow_radius, glow_radius + 1):
            for offset_y in range(-glow_radius, glow_radius + 1):
                if offset_x != 0 or offset_y != 0:
                    draw.text((x + offset_x, y + offset_y), text, font=font, 
                              fill=(*glow_color, 100), anchor="mm")
        
        # Draw main text
        draw.text(position, text, font=font, fill=fill, anchor="mm")
    
    def _center_text_glow(self, draw: ImageDraw, y: int, text: str, font: ImageFont, 
                          fill: str = "white", glow_color: Tuple[int, int, int] = (0, 0, 0)):
        """Draw centered text with glow at given y position"""
        x = self.width // 2
        self._add_text_with_glow(draw, (x, y), text, font, fill, glow_color)
    
    def create_title_slide(self, date_str: str) -> Image.Image:
        """Create the title/intro slide"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img, 'RGBA')
        
        # More centered vertically - start lower
        base_y = 450
        
        # Title
        self._center_text_glow(draw, base_y, "NC LOTTERY", self.fonts['title'], fill="#FFFFFF")
        self._center_text_glow(draw, base_y + 90, "SCRATCH OFF", self.fonts['title'], fill="#FFFFFF")
        
        # Stars instead of fire emoji + "BEST PICKS TODAY" + Date on same line
        self._center_text_glow(draw, base_y + 220, "* * * BEST PICKS * * *", self.fonts['rank'], fill="#00FFFF")
        self._center_text_glow(draw, base_y + 300, date_str, self.fonts['date'], fill="#FFD700")
        
        # Explanation - bolder and more prominent
        self._center_text_glow(draw, base_y + 430, "Games with the most TOP PRIZES", self.fonts['subtitle'], fill="#FFFFFF")
        self._center_text_glow(draw, base_y + 490, "remaining vs lowest prizes", self.fonts['subtitle'], fill="#E0E0FF")
        
        # Disclaimer box - dark background for contrast
        disclaimer_y = base_y + 620
        self._draw_rounded_rect(draw, 120, disclaimer_y - 30, self.width - 120, disclaimer_y + 100, 20, (0, 0, 0, 180))
        self._center_text_glow(draw, disclaimer_y + 10, "! Not financial advice !", self.fonts['disclaimer'], fill="#FFD700")
        self._center_text_glow(draw, disclaimer_y + 55, "Play responsibly", self.fonts['disclaimer'], fill="#FFFFFF")
        
        return img
    
    def create_game_slide(self, game: GameData, differential: float, 
                          rank: int, category: str, is_blurred: bool = False) -> Image.Image:
        """Create a slide for a specific game"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img, 'RGBA')
        
        # Centered vertically - rank header
        header_y = 200
        rank_text = f"#{rank} BEST {category}"
        self._center_text_glow(draw, header_y, rank_text, self.fonts['rank'], fill="#00FFFF")
        
        # Try to fetch and add game image
        game_img = None
        if game.image_url:
            game_img = self.analyzer.fetch_image(game.image_url)
        
        # Calculate image position (more centered)
        img_center_y = 750
        
        if game_img:
            # Resize game image - larger size
            img_aspect = game_img.width / game_img.height
            target_width = GAME_IMAGE_WIDTH
            target_height = int(target_width / img_aspect)
            
            # Limit height
            max_height = 950
            if target_height > max_height:
                target_height = max_height
                target_width = int(target_height * img_aspect)
            
            game_img = game_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
            
            # Apply blur if this is the #1 pick
            if is_blurred:
                game_img = game_img.filter(ImageFilter.GaussianBlur(radius=25))
            
            # Add white border/frame
            border_size = 12
            framed_img = Image.new('RGB', (target_width + border_size * 2, 
                                           target_height + border_size * 2), 'white')
            framed_img.paste(game_img, (border_size, border_size))
            
            # Center the game image
            img_x = (self.width - framed_img.width) // 2
            img_y = img_center_y - framed_img.height // 2
            
            # Paste shadow then image
            shadow_img = Image.new('RGB', framed_img.size, (0, 0, 0))
            img.paste(shadow_img, (img_x + 12, img_y + 12))
            img.paste(framed_img, (img_x, img_y))
            
            info_y = img_y + framed_img.height + 70
        else:
            # No image available - show game name instead
            self._center_text_glow(draw, img_center_y - 50, game.game_name, self.fonts['subtitle'], fill="#FFFFFF")
            self._center_text_glow(draw, img_center_y + 20, f"Game #{game.game_number}", self.fonts['disclaimer'], fill="#E0E0FF")
            info_y = img_center_y + 120
        
        # Refresh draw object after pasting images
        draw = ImageDraw.Draw(img, 'RGBA')
        
        # Draw dark background box for price/diff info
        self._draw_rounded_rect(draw, 100, info_y - 20, self.width - 100, info_y + 80, 15, (0, 0, 0, 200))
        
        # Price and differential with better colors
        price_text = f"${int(game.ticket_price)}"
        diff_text = f"Top Prize Diff: {differential:+.1f}%"
        
        self._center_text_glow(draw, info_y + 30, f"{price_text}  |  {diff_text}", 
                               self.fonts['info'], fill="#FFFFFF")
        
        # If blurred, add "Link in bio" prompt
        if is_blurred:
            self._draw_rounded_rect(draw, 80, info_y + 110, self.width - 80, info_y + 250, 15, (255, 215, 0, 230))
            draw.text((self.width // 2, info_y + 150), "Want to see the #1 pick?", 
                      font=self.fonts['disclaimer'], fill=(0, 0, 0), anchor="mm")
            draw.text((self.width // 2, info_y + 200), "LINK IN BIO for full rankings!", 
                      font=self.fonts['disclaimer'], fill=(50, 50, 100), anchor="mm")
        
        return img
    
    def create_divider_slide(self) -> Image.Image:
        """Create the budget picks divider slide"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img, 'RGBA')
        
        # Centered vertically
        center_y = self.height // 2
        
        # Money symbols instead of emoji
        self._center_text_glow(draw, center_y - 150, "$ $ $ NOW FOR $ $ $", self.fonts['rank'], fill="#FFD700")
        
        # Main text - bright white
        self._center_text_glow(draw, center_y, "BUDGET PICKS", self.fonts['title'], fill="#FFFFFF")
        
        # Under $10 text
        self._center_text_glow(draw, center_y + 150, "- - - Under $10 - - -", self.fonts['rank'], fill="#00FFFF")
        
        return img
    
    def create_cta_slide(self) -> Image.Image:
        """Create the call-to-action slide"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img, 'RGBA')
        
        # Centered vertically
        center_y = self.height // 2 - 100
        
        # Chart symbol
        self._center_text_glow(draw, center_y - 150, "[ RANKINGS ]", self.fonts['rank'], fill="#00FFFF")
        
        # Main CTA - bright and bold
        self._center_text_glow(draw, center_y, "FULL RANKINGS", self.fonts['title'], fill="#FFFFFF")
        self._center_text_glow(draw, center_y + 90, "+ DAILY UPDATES", self.fonts['rank'], fill="#00FFFF")
        
        # Link in bio - gold accent
        self._center_text_glow(draw, center_y + 220, "Link in bio", self.fonts['cta'], fill="#FFD700")
        
        # Engagement question box - white background
        box_top = center_y + 300
        self._draw_rounded_rect(draw, 100, box_top, self.width - 100, box_top + 220, 20, (255, 255, 255, 240))
        
        # Dark text on white box
        draw.text((self.width // 2, box_top + 50), "Which game are", font=self.fonts['cta'], 
                  fill=(50, 50, 80), anchor="mm")
        draw.text((self.width // 2, box_top + 110), "you trying?", font=self.fonts['cta'], 
                  fill=(50, 50, 80), anchor="mm")
        draw.text((self.width // 2, box_top + 175), "Comment below!", font=self.fonts['small'], 
                  fill=(100, 100, 140), anchor="mm")
        
        return img
    
    def generate_all_content(self, results: List[Tuple[GameData, float, float, float]], 
                             output_dir: str = "."):
        """Generate all slides and video - countdown format (3, 2, 1)"""
        
        # Filter and get top 3 for each category
        high_price = [(g, b, t, d) for g, b, t, d in results if g.ticket_price >= 10][:3]
        low_price = [(g, b, t, d) for g, b, t, d in results if g.ticket_price < 10][:3]
        
        # Use Eastern time for date
        eastern_now = get_eastern_time()
        date_str = eastern_now.strftime('%B %d, %Y')
        
        slides = []
        slide_durations = []
        
        print(f"\nGenerating slides for {date_str}...")
        
        # Slide 1: Title
        print("  Creating title slide...")
        title_slide = self.create_title_slide(date_str)
        title_slide.save(os.path.join(output_dir, "slide-1-title.png"))
        slides.append(title_slide)
        slide_durations.append(5)
        
        # Slides 2-4: $10+ games in REVERSE order (3, 2, 1) - #1 is blurred
        for i, (game, bottom, top, diff) in enumerate(reversed(high_price)):
            display_rank = 3 - i  # 3, 2, 1
            is_blurred = (display_rank == 1)
            print(f"  Creating $10+ game slide #{display_rank}{'(blurred)' if is_blurred else ''}...")
            slide = self.create_game_slide(game, diff, display_rank, "$10+", is_blurred=is_blurred)
            slide.save(os.path.join(output_dir, f"slide-{i+2}-game-{display_rank}-high.png"))
            slides.append(slide)
            slide_durations.append(5)
        
        # Slide 5: Divider
        print("  Creating divider slide...")
        divider_slide = self.create_divider_slide()
        divider_slide.save(os.path.join(output_dir, "slide-5-divider.png"))
        slides.append(divider_slide)
        slide_durations.append(2)
        
        # Slides 6-8: Under $10 games in REVERSE order (3, 2, 1) - #1 is blurred
        for i, (game, bottom, top, diff) in enumerate(reversed(low_price)):
            display_rank = 3 - i  # 3, 2, 1
            is_blurred = (display_rank == 1)
            print(f"  Creating under $10 game slide #{display_rank}{'(blurred)' if is_blurred else ''}...")
            slide = self.create_game_slide(game, diff, display_rank, "UNDER $10", is_blurred=is_blurred)
            slide.save(os.path.join(output_dir, f"slide-{i+6}-game-{display_rank}-low.png"))
            slides.append(slide)
            slide_durations.append(5)
        
        # Slide 9: CTA
        print("  Creating CTA slide...")
        cta_slide = self.create_cta_slide()
        cta_slide.save(os.path.join(output_dir, "slide-9-cta.png"))
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
            
            output_path = os.path.join(output_dir, "daily-reel.mp4")
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
    print("NC Lottery Reel Generator")
    print("=" * 60)
    
    eastern_now = get_eastern_time()
    print(f"Started at: {eastern_now.strftime('%Y-%m-%d %H:%M:%S')} Eastern")
    print()
    
    # Run analysis
    analyzer = NCLotteryAnalyzer(delay_seconds=0.5, verbose=True)
    results = analyzer.analyze_and_rank_games()
    
    if not results:
        print("\nERROR: No games found!")
        sys.exit(1)
    
    print(f"\nAnalysis complete! Found {len(results)} games.")
    
    # Generate reel and images
    generator = ReelGenerator(analyzer)
    generator.generate_all_content(results, output_dir=".")
    
    eastern_end = get_eastern_time()
    print(f"\nFinished at: {eastern_end.strftime('%Y-%m-%d %H:%M:%S')} Eastern")


if __name__ == "__main__":
    main()
