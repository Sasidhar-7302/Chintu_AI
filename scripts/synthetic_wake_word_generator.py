"""
Synthetic Wake Word Data Generator (gTTS Version)

Generates synthetic "Hey Chintu" samples using Google TTS.
Fast, reliable, with audio augmentation for training data diversity.
"""

import os
import random
from pathlib import Path
from typing import List, Tuple
import logging
import numpy as np
import time

logger = logging.getLogger(__name__)

# TTS
try:
    from gtts import gTTS
    HAS_GTTS = True
except ImportError:
    HAS_GTTS = False
    logger.warning("gtts not installed")

# Audio processing
try:
    import librosa
    import soundfile as sf
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False

try:
    from audiomentations import (
        Compose, AddGaussianNoise, TimeStretch, PitchShift,
        Shift, Gain
    )
    HAS_AUDIOMENTATIONS = True
except ImportError:
    HAS_AUDIOMENTATIONS = False


# Wake word phrases (variations)
POSITIVE_PHRASES = [
    "Hey Chintu",
]

# Negative phrases (phonetically similar)
NEGATIVE_PHRASES = [
    "Hey you",
    "Hey there", 
    "Hello there",
    "Hi there",
    "Hey Jarvis",
    "Hey Alexa",
    "Hey Siri",
    "OK Google",
    "Hey computer",
    "Good morning",
    "What time",
    "Turn on",
    "Hey buddy",
    "Hey friend",
    "Hey listen",
]

# Languages/accents in gTTS that sound different
GTTS_ACCENTS = [
    'en',      # English
    'en-us',   # US English  
    'en-uk',   # UK English
    'en-au',   # Australian
    'en-in',   # Indian English
]


class SyntheticWakeWordGenerator:
    """Generates synthetic wake word training data using gTTS and augmentation."""
    
    def __init__(
        self,
        output_dir: Path,
        sample_rate: int = 16000,
        positive_count: int = 50,
        negative_count: int = 100,
    ):
        self.output_dir = Path(output_dir)
        self.sample_rate = sample_rate
        self.positive_count = positive_count
        self.negative_count = negative_count
        
        # Create output directories
        self.positive_dir = self.output_dir / "positive"
        self.negative_dir = self.output_dir / "negative"
        self.positive_dir.mkdir(parents=True, exist_ok=True)
        self.negative_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup augmentation pipeline (more aggressive for diversity)
        self.augmenter = self._setup_augmentation()
    
    def _setup_augmentation(self):
        """Setup audio augmentation pipeline."""
        if not HAS_AUDIOMENTATIONS:
            return None
        
        return Compose([
            Gain(min_gain_db=-8, max_gain_db=8, p=0.6),
            AddGaussianNoise(min_amplitude=0.002, max_amplitude=0.025, p=0.5),
            TimeStretch(min_rate=0.8, max_rate=1.2, p=0.5),
            PitchShift(min_semitones=-4, max_semitones=4, p=0.5),
            Shift(min_shift=-0.2, max_shift=0.2, p=0.3),
        ])
    
    def generate_tts_sample(
        self,
        text: str,
        output_path: Path,
        lang: str = 'en',
    ) -> bool:
        """Generate a single TTS sample using gTTS."""
        if not HAS_GTTS:
            return False
        
        try:
            tts = gTTS(text=text, lang=lang, slow=False)
            mp3_path = output_path.with_suffix('.mp3')
            tts.save(str(mp3_path))
            
            # Convert to 16kHz wav
            if HAS_LIBROSA:
                audio, sr = librosa.load(str(mp3_path), sr=self.sample_rate)
                sf.write(str(output_path), audio, self.sample_rate)
                mp3_path.unlink()
            else:
                mp3_path.rename(output_path)
            
            return output_path.exists()
                
        except Exception as e:
            logger.warning(f"TTS generation failed for '{text}': {e}")
            return False
    
    def augment_and_save(self, audio: np.ndarray, base_path: Path, count: int = 5) -> int:
        """Create augmented versions of an audio sample."""
        if self.augmenter is None or not HAS_LIBROSA:
            return 0
        
        saved = 0
        for i in range(count):
            try:
                aug_audio = self.augmenter(samples=audio, sample_rate=self.sample_rate)
                aug_path = base_path.parent / f"{base_path.stem}_aug{i}.wav"
                sf.write(str(aug_path), aug_audio, self.sample_rate)
                saved += 1
            except Exception as e:
                logger.warning(f"Augmentation {i} failed: {e}")
        
        return saved
    
    def generate_positive_samples(self) -> int:
        """Generate positive wake word samples."""
        print(f"\n🎤 Generating positive samples...")
        
        total_files = 0
        base_count = max(1, self.positive_count // (len(GTTS_ACCENTS) * 5))  # Account for augmentations
        
        for idx, accent in enumerate(GTTS_ACCENTS):
            for i in range(base_count):
                phrase = random.choice(POSITIVE_PHRASES)
                sample_num = idx * base_count + i
                output_path = self.positive_dir / f"positive_{sample_num:04d}.wav"
                
                print(f"  [{sample_num+1}] Generating: '{phrase}' ({accent})...")
                
                success = self.generate_tts_sample(phrase, output_path, lang=accent)
                
                if success:
                    total_files += 1
                    
                    # Create augmented versions
                    if HAS_LIBROSA:
                        audio, sr = librosa.load(str(output_path), sr=self.sample_rate)
                        aug_count = self.augment_and_save(audio, output_path, count=5)
                        total_files += aug_count
                
                # Small delay to avoid rate limiting
                time.sleep(0.3)
        
        print(f"✅ Generated {total_files} positive samples (including augmentations)")
        return total_files
    
    def generate_negative_samples(self) -> int:
        """Generate negative samples."""
        print(f"\n🚫 Generating negative samples...")
        
        total_files = 0
        base_count = max(1, self.negative_count // len(NEGATIVE_PHRASES))
        
        for idx, phrase in enumerate(NEGATIVE_PHRASES):
            for i in range(min(base_count, 3)):  # Limit per phrase
                accent = random.choice(GTTS_ACCENTS)
                sample_num = idx * base_count + i
                output_path = self.negative_dir / f"negative_{sample_num:04d}.wav"
                
                if sample_num % 10 == 0:
                    print(f"  [{sample_num}] Generating negatives...")
                
                success = self.generate_tts_sample(phrase, output_path, lang=accent)
                
                if success:
                    total_files += 1
                
                time.sleep(0.2)
        
        print(f"✅ Generated {total_files} negative samples")
        return total_files
    
    def generate_all(self) -> Tuple[int, int]:
        """Generate all training samples."""
        print("\n" + "="*60)
        print("Synthetic Wake Word Data Generator")
        print("="*60)
        print(f"Output directory: {self.output_dir}")
        print(f"Using gTTS with audio augmentation")
        print("="*60)
        
        pos_count = self.generate_positive_samples()
        neg_count = self.generate_negative_samples()
        
        print("\n" + "="*60)
        print("Generation Complete!")
        print(f"  Positive samples: {pos_count}")
        print(f"  Negative samples: {neg_count}")
        print(f"  Total: {pos_count + neg_count}")
        print("="*60 + "\n")
        
        return pos_count, neg_count


def main():
    """Run the synthetic data generator."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate synthetic wake word training data")
    parser.add_argument("--output", type=str, default=None, help="Output directory")
    parser.add_argument("--positive", type=int, default=50, help="Target positive samples")
    parser.add_argument("--negative", type=int, default=100, help="Target negative samples")
    args = parser.parse_args()
    
    if args.output is None:
        output_dir = Path.home() / ".chintu" / "training_data"
    else:
        output_dir = Path(args.output)
    
    generator = SyntheticWakeWordGenerator(
        output_dir=output_dir,
        positive_count=args.positive,
        negative_count=args.negative,
    )
    
    generator.generate_all()
    
    print("\n📁 Next step: Run the trainer:")
    print(f"  python tools/train_custom_wake_word.py")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
