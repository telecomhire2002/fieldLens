import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Form, FormField, FormItem, FormLabel, FormControl, FormMessage,
} from "@/components/ui/form";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { createJob, type BackendJob } from "@/lib/api";

const phoneE164 = /^\+?[1-9]\d{6,14}$/;

const FormSchema = z.object({
  whatsappNumber: z.string().regex(phoneE164, "Use E.164 format like +1234567890"),
  siteId: z.string().min(1, "Site ID is required"),
  circle:z.string().min(1,"Circle is required"),
  company:z.string().min(1,"Company is required"),
  sectorNumber: z.string().min(1, "Sector is required"), // <-- NOW STRING
});

type FormValues = z.infer<typeof FormSchema>;

export default function CreateTaskDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (job: BackendJob) => void;
}) {
  const { toast } = useToast();

  const form = useForm<FormValues>({
    resolver: zodResolver(FormSchema),
    defaultValues: { whatsappNumber: "", siteId: "", sectorNumber: "",circle:"",company:"" },
    mode: "onSubmit",
  });

  const closeAndReset = () => {
    form.reset();
    onOpenChange(false);
  };

  const onSubmit = async (values: FormValues) => {
    try {
      const payload = {
        workerPhone: values.whatsappNumber,
        siteId: values.siteId.trim(),
        sector: values.sectorNumber.trim(), // <-- STRING NOW
        circle:values.circle.trim(),
        company:values.company.trim(),
      };

      const newJob = await createJob(payload);

      toast({
        title: "Job Saved",
        description:
          `Assigned sector "${payload.sector}" at site ${payload.siteId} to ${payload.workerPhone}.`,
      });

      onCreated?.(newJob);
      closeAndReset();
    } catch (e: any) {
      toast({
        title: "Create failed",
        description: e?.response?.data?.detail || e?.message || "Unknown error",
        variant: "destructive",
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(o) : closeAndReset())}>
      <DialogContent className="max-w-2xl p-0 overflow-hidden">
        <DialogHeader className="px-6 pt-6">
          <DialogTitle>Create / Merge Sector</DialogTitle>
          <DialogDescription>
            Create a job for a worker and a site. If the worker+site already exists, the sector will be merged.
          </DialogDescription>
        </DialogHeader>

        <Card className="shadow-none border-0">
          <CardHeader className="px-6 pt-0">
            <CardTitle className="text-base text-muted-foreground">Task Details</CardTitle>
          </CardHeader>
          <CardContent className="px-6 pb-6">
            <Form {...form}>
              <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  
                  <FormField
                    control={form.control}
                    name="whatsappNumber"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>WhatsApp Number *</FormLabel>
                        <FormControl>
                          <Input placeholder="+91..." {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="siteId"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Site ID *</FormLabel>
                        <FormControl>
                          <Input placeholder="e.g. BHOPAL-1234" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="circle"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Circle </FormLabel>
                        <FormControl>
                          <Input placeholder="e.g. Delhi" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="company"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Company *</FormLabel>
                        <FormControl>
                          <Input {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="sectorNumber"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Sector *</FormLabel>
                        <FormControl>
                          <Input type="text" placeholder="e.g. A-12, North-2, etc." {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                </div>

                <DialogFooter className="gap-2 sm:gap-3">
                  <Button type="button" variant="outline" onClick={closeAndReset}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={form.formState.isSubmitting} className="min-w-28">
                    {form.formState.isSubmitting ? "Saving…" : "Save"}
                  </Button>
                </DialogFooter>
              </form>
            </Form>
          </CardContent>
        </Card>
      </DialogContent>
    </Dialog>
  );
}
