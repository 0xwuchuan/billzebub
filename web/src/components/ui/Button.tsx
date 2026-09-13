import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "outline" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
};

const variantClass: Record<Variant, string> = {
  primary: "btn btn-primary",
  ghost: "btn btn-ghost",
  outline: "btn btn-outline",
  danger: "btn btn-danger",
};

export function Button({
  variant = "outline",
  className,
  type = "button",
  ...props
}: ButtonProps) {
  const classes =
    className === undefined
      ? variantClass[variant]
      : `${variantClass[variant]} ${className}`;
  return <button className={classes} type={type} {...props} />;
}
