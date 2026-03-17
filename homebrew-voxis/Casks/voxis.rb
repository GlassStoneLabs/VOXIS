cask "voxis" do
  version "4.0.0"
  sha256 "c9dca7c515f52d857109296885a7bb67f91d8ecba2b79238645d570dc3d86b5e"

  url "https://github.com/GlassStoneLabs/VOXIS/releases/download/v#{version}/Voxis-#{version}-arm64.dmg"
  name "Voxis"
  desc "Professional audio restoration powered by Trinity V8.1 — Glass Stone LLC"
  homepage "https://github.com/GlassStoneLabs/VOXIS"

  depends_on macos: ">= :monterey"
  depends_on arch: :arm64

  app "Voxis.app"

  zap trash: [
    "~/Library/Application Support/Voxis",
    "~/Library/Preferences/com.glassstone.voxis.plist",
    "~/Library/Caches/com.glassstone.voxis",
    "~/.voxis",
  ]

  caveats <<~EOS
    Voxis requires FFmpeg for audio decoding:
      brew install ffmpeg

    Restored audio files are saved to:
      ~/Music/Voxis Restored/
  EOS
end
