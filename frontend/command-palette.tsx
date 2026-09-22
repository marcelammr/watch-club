import { useEffect, useState } from "react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";

type CommandItemData = {
  label: string;
  href: string;
};

type CommandGroupData = {
  heading: string;
  items: CommandItemData[];
};

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<CommandGroupData[]>([]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "k" || !(event.metaKey || event.ctrlKey)) {
        return;
      }
      event.preventDefault();
      setOpen((value) => !value);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    fetch("/api/command")
      .then((response) => response.json())
      .then((data: { groups?: CommandGroupData[] }) => setGroups(data.groups ?? []))
      .catch(() => setGroups([]));
  }, [open]);

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Buscar páginas e clubes…" />
      <CommandList>
        <CommandEmpty>Nenhum resultado.</CommandEmpty>
        {groups.map((group, index) => (
          <div key={group.heading}>
            {index > 0 ? <CommandSeparator /> : null}
            <CommandGroup heading={group.heading}>
              {group.items.map((item) => (
                <CommandItem
                  key={`${group.heading}-${item.href}-${item.label}`}
                  value={`${group.heading} ${item.label}`}
                  onSelect={() => {
                    setOpen(false);
                    window.location.assign(item.href);
                  }}
                >
                  {item.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </div>
        ))}
      </CommandList>
    </CommandDialog>
  );
}
