"""
NC Lottery Reel Generator - GitHub Actions Version
===================================================

This script generates a daily Instagram Reel video and standalone images
featuring the top NC Lottery scratch-off games.

It scrapes data from the NC Lottery website and creates:
- 1 MP4 video (Reel) with all slides
- 9 PNG images (each slide as standalone)

Output is deployed to GitHub Pages for easy access.
"""

import requests
from bs4 import BeautifulSoup
import re
import time
from typing import List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import sys
import io

# Try to import moviepy components
try:
    from moviepy.editor import (
        ImageClip, concatenate_videoclips, CompositeVideoClip
    )
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    print("Warning: moviepy not available, video generation will be skipped")


# Constants
REEL_WIDTH = 1080
REEL_HEIGHT = 1920
GAME_IMAGE_WIDTH = 700
TRANSITION_DURATION = 0.3


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
            # Look for the main game/ticket image
            if 'scratch' in src.lower() or 'game' in alt or 'ticket' in alt:
                if src.startswith('/'):
                    image_url = self.BASE_URL + src
                elif src.startswith('http'):
                    image_url = src
                break
        
        # Fallback: look for any large image that might be the ticket
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
        
        # Try to load fonts, fall back to default if not available
        self.fonts = self._load_fonts()
        
    def _load_fonts(self) -> dict:
        """Load fonts with fallbacks"""
        fonts = {}
        
        # Font paths to try (common locations)
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
        
        # If no fonts found, use default
        if not bold_font_path:
            bold_font_path = regular_font_path
        if not regular_font_path:
            regular_font_path = bold_font_path
            
        try:
            fonts['title'] = ImageFont.truetype(bold_font_path, 72) if bold_font_path else ImageFont.load_default()
            fonts['subtitle'] = ImageFont.truetype(regular_font_path, 42) if regular_font_path else ImageFont.load_default()
            fonts['rank'] = ImageFont.truetype(bold_font_path, 64) if bold_font_path else ImageFont.load_default()
            fonts['info'] = ImageFont.truetype(bold_font_path, 56) if bold_font_path else ImageFont.load_default()
            fonts['disclaimer'] = ImageFont.truetype(regular_font_path, 32) if regular_font_path else ImageFont.load_default()
            fonts['cta'] = ImageFont.truetype(bold_font_path, 48) if bold_font_path else ImageFont.load_default()
            fonts['emoji'] = ImageFont.truetype(regular_font_path, 80) if regular_font_path else ImageFont.load_default()
        except Exception as e:
            print(f"Font loading error: {e}, using defaults")
            default = ImageFont.load_default()
            fonts = {k: default for k in ['title', 'subtitle', 'rank', 'info', 'disclaimer', 'cta', 'emoji']}
        
        return fonts
    
    def _create_gradient_background(self) -> Image.Image:
        """Create a gold to orange gradient background"""
        img = Image.new('RGB', (self.width, self.height))
        draw = ImageDraw.Draw(img)
        
        # Gold (#FFD700) to Orange (#FF8C00) gradient
        start_color = (255, 215, 0)  # Gold
        end_color = (255, 140, 0)    # Dark Orange
        
        for y in range(self.height):
            ratio = y / self.height
            r = int(start_color[0] + (end_color[0] - start_color[0]) * ratio)
            g = int(start_color[1] + (end_color[1] - start_color[1]) * ratio)
            b = int(start_color[2] + (end_color[2] - start_color[2]) * ratio)
            draw.line([(0, y), (self.width, y)], fill=(r, g, b))
        
        return img
    
    def _add_text_with_shadow(self, draw: ImageDraw, position: Tuple[int, int], 
                              text: str, font: ImageFont, fill: str = "white",
                              shadow_offset: int = 3, anchor: str = None):
        """Add text with drop shadow for readability"""
        x, y = position
        # Shadow
        draw.text((x + shadow_offset, y + shadow_offset), text, font=font, 
                  fill=(0, 0, 0, 128), anchor=anchor)
        # Main text
        draw.text(position, text, font=font, fill=fill, anchor=anchor)
    
    def _center_text(self, draw: ImageDraw, y: int, text: str, font: ImageFont, 
                     fill: str = "white", shadow_offset: int = 3):
        """Draw centered text at given y position"""
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        x = (self.width - text_width) // 2
        self._add_text_with_shadow(draw, (x, y), text, font, fill, shadow_offset)
    
    def create_title_slide(self, date_str: str) -> Image.Image:
        """Create the title/intro slide"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img)
        
        # Title
        self._center_text(draw, 350, "NC LOTTERY", self.fonts['title'])
        self._center_text(draw, 440, "SCRATCH OFF", self.fonts['title'])
        
        # Fire emoji and "BEST PICKS TODAY"
        self._center_text(draw, 580, "🔥 BEST PICKS TODAY 🔥", self.fonts['rank'])
        
        # Date
        self._center_text(draw, 700, date_str, self.fonts['subtitle'])
        
        # Explanation
        self._center_text(draw, 850, "These games have the most", self.fonts['subtitle'])
        self._center_text(draw, 910, "top prizes available relative to", self.fonts['subtitle'])
        self._center_text(draw, 970, "the lowest prizes", self.fonts['subtitle'])
        
        # Disclaimer box
        disclaimer_y = 1150
        draw.rectangle([(100, disclaimer_y - 20), (self.width - 100, disclaimer_y + 120)], 
                       fill=(0, 0, 0, 80))
        self._center_text(draw, disclaimer_y, "⚠️ Not financial advice", self.fonts['disclaimer'])
        self._center_text(draw, disclaimer_y + 50, "Play responsibly", self.fonts['disclaimer'])
        
        return img
    
    def create_game_slide(self, game: GameData, differential: float, 
                          rank: int, category: str) -> Image.Image:
        """Create a slide for a specific game"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img)
        
        # Rank header
        rank_text = f"#{rank} BEST {category}"
        self._center_text(draw, 150, rank_text, self.fonts['rank'])
        
        # Try to fetch and add game image
        game_img = None
        if game.image_url:
            game_img = self.analyzer.fetch_image(game.image_url)
        
        if game_img:
            # Resize game image to fit
            img_aspect = game_img.width / game_img.height
            target_width = GAME_IMAGE_WIDTH
            target_height = int(target_width / img_aspect)
            
            # Limit height
            max_height = 900
            if target_height > max_height:
                target_height = max_height
                target_width = int(target_height * img_aspect)
            
            game_img = game_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
            
            # Add white border/frame
            border_size = 10
            framed_img = Image.new('RGB', (target_width + border_size * 2, 
                                           target_height + border_size * 2), 'white')
            framed_img.paste(game_img, (border_size, border_size))
            
            # Add shadow effect
            shadow = Image.new('RGBA', framed_img.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.rectangle([(0, 0), shadow.size], fill=(0, 0, 0, 50))
            
            # Center the game image
            img_x = (self.width - framed_img.width) // 2
            img_y = 350
            
            # Paste shadow then image
            img.paste(framed_img, (img_x + 8, img_y + 8))  # Shadow offset
            img.paste(framed_img, (img_x, img_y))
            
            info_y = img_y + framed_img.height + 80
        else:
            # No image available - show game name instead
            self._center_text(draw, 600, game.game_name, self.fonts['subtitle'])
            self._center_text(draw, 680, f"Game #{game.game_number}", self.fonts['disclaimer'])
            info_y = 900
        
        # Price and differential
        price_text = f"${int(game.ticket_price)}"
        diff_text = f"Diff: {differential:+.1f}%"
        diff_color = "#00FF00" if differential > 0 else "#FF4444"
        
        self._center_text(draw, info_y, f"{price_text}  |  {diff_text}", 
                          self.fonts['info'], fill="white")
        
        return img
    
    def create_divider_slide(self) -> Image.Image:
        """Create the budget picks divider slide"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img)
        
        # Create a slightly darker overlay for emphasis
        overlay = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 40))
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(img)
        
        # Money emoji row
        self._center_text(draw, 650, "💰 NOW FOR 💰", self.fonts['rank'])
        
        # Main text
        self._center_text(draw, 800, "BUDGET PICKS", self.fonts['title'])
        
        # Ticket emoji row
        self._center_text(draw, 950, "🎫 Under $10 🎫", self.fonts['rank'])
        
        return img
    
    def create_cta_slide(self) -> Image.Image:
        """Create the call-to-action slide"""
        img = self._create_gradient_background()
        draw = ImageDraw.Draw(img)
        
        # Chart emoji
        self._center_text(draw, 450, "📊", self.fonts['emoji'])
        
        # Main CTA
        self._center_text(draw, 600, "FULL RANKINGS", self.fonts['title'])
        self._center_text(draw, 700, "+ DAILY UPDATES", self.fonts['rank'])
        
        # Link in bio
        self._center_text(draw, 880, "Link in bio", self.fonts['cta'])
        
        # Engagement question
        draw.rectangle([(80, 1050), (self.width - 80, 1250)], 
                       fill=(255, 255, 255, 60))
        self._center_text(draw, 1080, "💬 Which game are", self.fonts['cta'])
        self._center_text(draw, 1150, "you trying?", self.fonts['cta'])
        self._center_text(draw, 1250, "Comment below!", self.fonts['subtitle'])
        
        return img
    
    def generate_all_content(self, results: List[Tuple[GameData, float, float, float]], 
                             output_dir: str = "."):
        """Generate all slides and video"""
        
        # Filter and get top 3 for each category
        high_price = [(g, b, t, d) for g, b, t, d in results if g.ticket_price >= 10][:3]
        low_price = [(g, b, t, d) for g, b, t, d in results if g.ticket_price < 10][:3]
        
        date_str = datetime.now().strftime('%B %d, %Y')
        
        slides = []
        slide_durations = []
        
        print("\nGenerating slides...")
        
        # Slide 1: Title
        print("  Creating title slide...")
        title_slide = self.create_title_slide(date_str)
        title_slide.save(os.path.join(output_dir, "slide-1-title.png"))
        slides.append(title_slide)
        slide_durations.append(5)
        
        # Slides 2-4: Top 3 $10+ games
        for i, (game, bottom, top, diff) in enumerate(high_price, 1):
            print(f"  Creating $10+ game slide #{i}...")
            slide = self.create_game_slide(game, diff, i, "$10+")
            slide.save(os.path.join(output_dir, f"slide-{i+1}-game-{i}-high.png"))
            slides.append(slide)
            slide_durations.append(5)
        
        # Slide 5: Divider
        print("  Creating divider slide...")
        divider_slide = self.create_divider_slide()
        divider_slide.save(os.path.join(output_dir, "slide-5-divider.png"))
        slides.append(divider_slide)
        slide_durations.append(2)
        
        # Slides 6-8: Top 3 under $10 games
        for i, (game, bottom, top, diff) in enumerate(low_price, 1):
            print(f"  Creating under $10 game slide #{i}...")
            slide = self.create_game_slide(game, diff, i, "UNDER $10")
            slide.save(os.path.join(output_dir, f"slide-{i+5}-game-{i}-low.png"))
            slides.append(slide)
            slide_durations.append(5)
        
        # Slide 9: CTA
        print("  Creating CTA slide...")
        cta_slide = self.create_cta_slide()
        cta_slide.save(os.path.join(output_dir, "slide-9-cta.png"))
        slides.append(cta_slide)
        slide_durations.append(4)
        
        print(f"\n✓ Generated {len(slides)} standalone images")
        
        # Generate video if moviepy is available
        if MOVIEPY_AVAILABLE:
            print("\nGenerating video...")
            self._create_video(slides, slide_durations, output_dir)
        else:
            print("\n⚠ Video generation skipped (moviepy not available)")
        
        return slides
    
    def _create_video(self, slides: List[Image.Image], durations: List[int], 
                      output_dir: str):
        """Create the video with push transitions"""
        
        clips = []
        
        for i, (slide, duration) in enumerate(zip(slides, durations)):
            # Convert PIL Image to numpy array for moviepy
            import numpy as np
            slide_array = np.array(slide)
            
            clip = ImageClip(slide_array).set_duration(duration)
            clips.append(clip)
        
        # Concatenate with crossfade (simulating push effect)
        # Note: True push transition requires more complex compositing
        # Using crossfade as a simpler alternative that looks clean
        final_clips = []
        for i, clip in enumerate(clips):
            if i == 0:
                final_clips.append(clip)
            else:
                # Add small crossfade transition
                final_clips.append(clip.crossfadein(TRANSITION_DURATION))
        
        final_video = concatenate_videoclips(final_clips, method="compose")
        
        output_path = os.path.join(output_dir, "daily-reel.mp4")
        final_video.write_videofile(
            output_path,
            fps=30,
            codec='libx264',
            audio=False,
            preset='medium',
            threads=2
        )
        
        print(f"✓ Video saved to: {output_path}")


def main():
    """Main execution function"""
    print("=" * 60)
    print("NC Lottery Reel Generator")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
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
    
    print(f"\nFinished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")


if __name__ == "__main__":
    main()
