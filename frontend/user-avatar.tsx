import { createRoot, type Root } from "react-dom/client";
import { Avatar, AvatarBadge, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import type { BadgeProps } from "@/components/ui/badge";

const sizes = {
  sm: "h-8 w-8",
  md: "h-10 w-10",
  lg: "h-[88px] w-[88px] text-2xl",
} as const;

const badgeSizes = {
  sm: "size-2.5",
  md: "size-3",
  lg: "size-4",
} as const;

const presenceVariant: Record<string, NonNullable<BadgeProps["variant"]>> = {
  online: "accessory",
  away: "secondary",
  offline: "outline",
};

const presenceClass: Record<string, string> = {
  online: "bg-[#3ddc84] hover:bg-[#3ddc84]",
  away: "overflow-hidden bg-background p-0 text-chart-1 hover:bg-background",
  offline: "bg-muted-foreground",
};

function CrescentMoon() {
  return (
    <svg className="presence-moon h-full w-full" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M13.2 10.15A6.2 6.2 0 0 1 5.85 2.8 6.35 6.35 0 1 0 13.2 13.6a6.2 6.2 0 0 1 0-3.45z" />
    </svg>
  );
}

export type AvatarSize = keyof typeof sizes;

type UserAvatarProps = {
  src: string;
  alt: string;
  fallback: string;
  presence?: string;
  presenceLabel?: string;
  size?: AvatarSize;
  className?: string;
};

export function UserAvatar({
  src,
  alt,
  fallback,
  presence,
  presenceLabel,
  size = "md",
  className,
}: UserAvatarProps) {
  const status = presence && presence in presenceVariant ? presence : undefined;
  return (
    <Avatar className={cn(sizes[size], className)}>
      <AvatarImage src={src} alt={alt} />
      <AvatarFallback>{fallback}</AvatarFallback>
      {status ? (
        <AvatarBadge
          variant={presenceVariant[status]}
          className={cn(badgeSizes[size], presenceClass[status])}
          title={presenceLabel}
          aria-label={presenceLabel}
        >
          {status === "away" ? <CrescentMoon /> : null}
        </AvatarBadge>
      ) : null}
    </Avatar>
  );
}

const avatarRoots = new WeakMap<HTMLElement, Root>();

export function mountUserAvatars(root: ParentNode = document) {
  root.querySelectorAll<HTMLElement>("[data-user-avatar]").forEach((node) => {
    if (node.dataset.mounted === "true") {
      return;
    }
    const src = node.dataset.src;
    if (!src) {
      return;
    }
    node.dataset.mounted = "true";
    let reactRoot = avatarRoots.get(node);
    if (!reactRoot) {
      reactRoot = createRoot(node);
      avatarRoots.set(node, reactRoot);
    }
    reactRoot.render(
      <UserAvatar
        src={src}
        alt={node.dataset.alt || ""}
        fallback={node.dataset.fallback || "?"}
        presence={node.dataset.presence}
        presenceLabel={node.dataset.presenceLabel}
        size={(node.dataset.size as AvatarSize) || "md"}
      />
    );
  });
}

export function remountUserAvatars(root: ParentNode = document) {
  root.querySelectorAll<HTMLElement>("[data-user-avatar]").forEach((node) => {
    node.dataset.mounted = "false";
  });
  mountUserAvatars(root);
}
