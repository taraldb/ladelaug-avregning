import { inputClass } from "../lib/ui";
interface DateFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  name?: string;
  required?: boolean;
  hint?: string;
}

export default function DateField({
  label,
  value,
  onChange,
  name,
  required,
  hint,
}: DateFieldProps) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-300">{label}</span>
      <input
        type="date"
        name={name}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={inputClass}
      />
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}
