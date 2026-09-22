import { createRoot } from "react-dom/client";
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
  away: "",
  offline: "bg-muted-foreground",
};

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
        />
      ) : null}
    </Avatar>
  );
}

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
    createRoot(node).render(
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
