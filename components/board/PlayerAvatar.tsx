import Image from "next/image";

function initials(name: string): string {
  return name
    .split(" ")
    .slice(0, 2)
    .map((part) => part[0] ?? "")
    .join("");
}

/**
 * A player's headshot bordered in his team's primary colour, with the team logo
 * badged on the corner. Both URLs and the colour come from the nflverse feeds;
 * a player the feed has no photo for falls back to his initials rather than a
 * broken image.
 *
 * `unoptimized` on purpose: the NFL media CDN already serves these through its
 * own `f_auto,q_auto` transform, so running them through Next's optimizer again
 * would add a round trip to re-compress an already-compressed 36px image.
 */
export function PlayerAvatar({
  name,
  headshotUrl,
  logoUrl,
  colorPrimary,
  teamAbbr,
}: {
  name: string;
  headshotUrl: string | null;
  logoUrl: string | null;
  colorPrimary: string | null;
  teamAbbr: string;
}) {
  return (
    <span className="relative inline-flex size-9 shrink-0">
      <span
        className="flex size-9 items-center justify-center overflow-hidden rounded-full border-2 bg-surface"
        style={{ borderColor: colorPrimary ?? "var(--border)" }}
      >
        {headshotUrl ? (
          <Image
            src={headshotUrl}
            alt=""
            width={36}
            height={36}
            className="size-9 object-cover"
            unoptimized
          />
        ) : (
          <span className="text-[10px] font-semibold text-muted">{initials(name)}</span>
        )}
      </span>
      {logoUrl && (
        <Image
          src={logoUrl}
          alt={teamAbbr}
          width={16}
          height={16}
          className="absolute -bottom-0.5 -right-1 size-4 rounded-full bg-background"
          unoptimized
        />
      )}
    </span>
  );
}
