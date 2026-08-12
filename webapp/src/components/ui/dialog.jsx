import * as React from "react"
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
import { XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

function Dialog(props) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

function DialogPortal(props) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />
}

function DialogOverlay({ className, ...props }) {
  return (
    <DialogPrimitive.Backdrop
      data-slot="dialog-overlay"
      className={cn(
        "fixed inset-0 z-50 bg-black/20 transition-opacity duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0",
        className,
      )}
      {...props}
    />
  )
}

function DialogContent({ className, children, showCloseButton = true, ...props }) {
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Popup
        data-slot="dialog-content"
        className={cn(
          "fixed top-1/2 left-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-[680px] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border bg-popover text-popover-foreground shadow-xl transition-opacity duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0",
          className,
        )}
        {...props}
      >
        {children}
        {showCloseButton ? (
          <DialogPrimitive.Close
            data-slot="dialog-close"
            render={<Button className="absolute top-3 right-3" size="icon-sm" variant="ghost" />}
          >
            <XIcon />
            <span className="sr-only">닫기</span>
          </DialogPrimitive.Close>
        ) : null}
      </DialogPrimitive.Popup>
    </DialogPortal>
  )
}

function DialogHeader({ className, ...props }) {
  return <div className={cn("flex flex-col gap-1 p-4", className)} data-slot="dialog-header" {...props} />
}

function DialogTitle({ className, ...props }) {
  return (
    <DialogPrimitive.Title
      className={cn("text-base font-medium text-foreground", className)}
      data-slot="dialog-title"
      {...props}
    />
  )
}

function DialogDescription({ className, ...props }) {
  return (
    <DialogPrimitive.Description
      className={cn("text-sm text-muted-foreground", className)}
      data-slot="dialog-description"
      {...props}
    />
  )
}

export {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
}
