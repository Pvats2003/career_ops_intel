import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import { Button, Card, ErrorBanner, LoadingState } from '../components/ui'
import type { CandidateProfileOut, ResumeUploadResult } from '../types'

export default function Resume() {
  const [profile, setProfile] = useState<CandidateProfileOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [uploadResult, setUploadResult] = useState<ResumeUploadResult | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const load = () => {
    api
      .candidateProfile()
      .then(setProfile)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Failed to load profile.'))
  }

  useEffect(load, [])

  const handleUpload = async (file: File) => {
    setUploading(true)
    setError(null)
    setUploadResult(null)
    try {
      const result = await api.uploadResume(file)
      setUploadResult(result)
      load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  if (error && !profile) return <ErrorBanner message={error} />
  if (!profile) return <LoadingState />

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50">Resume</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Your structured candidate profile, parsed from your resume and knowledge base.
        </p>
      </div>

      <Card className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Replace resume file
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              .docx only — re-parses and re-validates your profile against it. Never
              auto-attached to any application.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={fileInput}
              type="file"
              accept=".docx"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
            />
            <Button
              variant="primary"
              onClick={() => fileInput.current?.click()}
              disabled={uploading}
            >
              {uploading ? 'Uploading…' : 'Upload .docx'}
            </Button>
          </div>
        </div>
        {error && (
          <div className="mt-3">
            <ErrorBanner message={error} />
          </div>
        )}
        {uploadResult && (
          <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-800 dark:bg-slate-800/50">
            <div className="font-medium text-slate-800 dark:text-slate-100">
              Validation: {uploadResult.validation_status}
            </div>
            {uploadResult.issues.length > 0 && (
              <ul className="mt-1 list-inside list-disc text-slate-600 dark:text-slate-400">
                {uploadResult.issues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </Card>

      <Card className="p-6">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Name</div>
            <div className="font-medium text-slate-900 dark:text-slate-50">{profile.name}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Location</div>
            <div className="font-medium text-slate-900 dark:text-slate-50">
              {profile.current_location}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Email</div>
            <div className="font-medium text-slate-900 dark:text-slate-50">{profile.email}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Phone</div>
            <div className="font-medium text-slate-900 dark:text-slate-50">{profile.phone}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Years of experience</div>
            <div className="font-medium text-slate-900 dark:text-slate-50">
              {profile.years_experience}
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">LinkedIn</div>
            <a
              href={profile.linkedin}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            >
              {profile.linkedin}
            </a>
          </div>
        </div>
      </Card>

      {profile.target_roles_primary.length > 0 && (
        <Card className="p-6">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            Target roles
          </h2>
          <div className="mt-2 flex flex-wrap gap-2">
            {profile.target_roles_primary.map((role) => (
              <span
                key={role}
                className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300"
              >
                {role}
              </span>
            ))}
          </div>
        </Card>
      )}

      <Card className="p-6">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Skills</h2>
        <div className="mt-2 flex flex-wrap gap-2">
          {profile.skills.map((skill) => (
            <span
              key={skill}
              className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300"
            >
              {skill}
            </span>
          ))}
        </div>
      </Card>

      {profile.experience.length > 0 && (
        <Card className="p-6">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Experience</h2>
          <div className="mt-3 flex flex-col gap-4">
            {profile.experience.map((exp, i) => (
              <div key={i} className="border-l-2 border-slate-200 pl-3 dark:border-slate-700">
                <div className="text-sm font-medium text-slate-900 dark:text-slate-50">
                  {String(exp.title)} · {String(exp.company)}
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {String(exp.start_date)} – {String(exp.end_date)}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
