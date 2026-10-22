import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    // The two hosts nflverse's own feeds point at: ESPN for team logos
    // (teams.logo_url) and NFL's media CDN for player headshots
    // (players.headshot_url). Both URLs come from the feed, never hand-built,
    // so this list is the only place the hostnames are written down.
    remotePatterns: [
      { protocol: "https", hostname: "a.espncdn.com" },
      { protocol: "https", hostname: "static.www.nfl.com" },
    ],
  },
};

export default nextConfig;
