import React, { useState, useEffect } from 'react';
import {
  Plus, Search, Upload, RefreshCw, Sparkles, Trash2, Camera, Check,
  AlertCircle, Pencil, CheckSquare, Square, Undo2, X, Eye, AlertTriangle
} from 'lucide-react';
import { Product } from '../types';
import { api } from '../services/api';

interface Props {
  onStart360Scan: (product: Product) => void;
}

export const ProductCatalogView: React.FC<Props> = ({ onStart360Scan }) => {
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('All');
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Edit Product State
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [editingProd, setEditingProd] = useState<Product | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);

  // Bulk Selection State
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  // Product Detail Modal State
  const [detailProduct, setDetailProduct] = useState<Product | null>(null);

  // Delete & Undo State
  const [deleteTarget, setDeleteTarget] = useState<
    { type: 'SINGLE'; product: Product } | { type: 'BULK'; count: number; ids: string[] } | null
  >(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [undoToast, setUndoToast] = useState<{ id?: string; name: string } | null>(null);
  const [undoTimer, setUndoTimer] = useState<any>(null);

  // CSV Import State
  const [isImporting, setIsImporting] = useState(false);

  const [newProd, setNewProd] = useState({
    name: '',
    brand: '',
    barcode: '',
    category: 'Dairy',
    price: 99.0,
    weight_grams: 250,
    stock_quantity: 100,
    tax_rate: 5.0,
  });

  const loadProducts = async () => {
    try {
      const data = await api.getProducts(search, category);
      setProducts(data);
    } catch (e) {
      console.error('Error fetching products:', e);
    }
  };

  useEffect(() => {
    loadProducts();
  }, [search, category]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddError(null);

    // Client-side duplicate barcode check
    const cleanBarcode = newProd.barcode.trim();
    const existing = products.find((p) => p.barcode.trim().toLowerCase() === cleanBarcode.toLowerCase());
    if (existing) {
      setAddError(`Barcode "${cleanBarcode}" is already in use by "${existing.name}". Every item must have a unique barcode.`);
      return;
    }

    setIsSaving(true);
    try {
      await api.createProduct({ ...newProd, barcode: cleanBarcode });
      setIsAddOpen(false);
      setNewProd({
        name: '',
        brand: '',
        barcode: '',
        category: 'Dairy',
        price: 99.0,
        weight_grams: 250,
        stock_quantity: 100,
        tax_rate: 5.0,
      });
      await loadProducts();
    } catch (err: any) {
      setAddError(err.message || 'Failed to save product to database.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleCreateAndScan = async () => {
    setAddError(null);
    if (!newProd.name || !newProd.barcode) {
      setAddError('Please fill in product name and barcode before starting 360 scan.');
      return;
    }

    const cleanBarcode = newProd.barcode.trim();
    const existing = products.find((p) => p.barcode.trim().toLowerCase() === cleanBarcode.toLowerCase());
    if (existing) {
      setAddError(`Barcode "${cleanBarcode}" is already in use by "${existing.name}". Every item must have a unique barcode.`);
      return;
    }

    setIsSaving(true);
    try {
      const created = await api.createProduct({ ...newProd, barcode: cleanBarcode });
      setIsAddOpen(false);
      await loadProducts();
      onStart360Scan(created);
    } catch (err: any) {
      setAddError(err.message || 'Failed to save product to database.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleOpenEdit = (prod: Product) => {
    setEditingProd({ ...prod });
    setEditError(null);
    setIsEditOpen(true);
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingProd) return;
    setEditError(null);

    const cleanBarcode = editingProd.barcode.trim();
    const existing = products.find(
      (p) => p.id !== editingProd.id && p.barcode.trim().toLowerCase() === cleanBarcode.toLowerCase()
    );
    if (existing) {
      setEditError(`Barcode "${cleanBarcode}" is already in use by "${existing.name}". Please provide a unique barcode.`);
      return;
    }

    setIsUpdating(true);
    try {
      await api.updateProduct(editingProd.id, {
        name: editingProd.name,
        brand: editingProd.brand,
        barcode: cleanBarcode,
        category: editingProd.category,
        price: Number(editingProd.price),
        discount_price: editingProd.discount_price ? Number(editingProd.discount_price) : undefined,
        weight_grams: Number(editingProd.weight_grams),
        tax_rate: Number(editingProd.tax_rate),
        stock_quantity: Number(editingProd.stock_quantity),
        primary_image_url: editingProd.primary_image_url,
      });
      setIsEditOpen(false);
      setEditingProd(null);
      await loadProducts();
    } catch (err: any) {
      setEditError(err.message || 'Failed to update product record in database.');
    } finally {
      setIsUpdating(false);
    }
  };

  const handleCSVUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsImporting(true);
    try {
      const res = await api.bulkUploadCSV(file);
      alert(`Bulk CSV Import complete!\n• Successfully added/updated: ${res.success_count}\n• Errors: ${res.error_count}`);
      await loadProducts();
    } catch (err: any) {
      alert(`CSV Upload failed: ${err.message || 'Failed to process CSV file'}`);
    } finally {
      setIsImporting(false);
      e.target.value = '';
    }
  };

  const handleOpenDeleteSingle = (prod: Product, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setDeleteError(null);
    setDeleteTarget({ type: 'SINGLE', product: prod });
  };

  const handleOpenDeleteBulk = () => {
    if (selectedIds.length === 0) return;
    setDeleteError(null);
    setDeleteTarget({ type: 'BULK', count: selectedIds.length, ids: selectedIds });
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    setDeleteError(null);

    try {
      if (deleteTarget.type === 'SINGLE') {
        const prod = deleteTarget.product;
        await api.deleteProduct(prod.id);
        setDeleteTarget(null);
        if (detailProduct?.id === prod.id) setDetailProduct(null);
        setSelectedIds((prev) => prev.filter((id) => id !== prod.id));

        // Start 7-second undo window
        if (undoTimer) clearTimeout(undoTimer);
        setUndoToast({ id: prod.id, name: prod.name });
        const timer = setTimeout(() => {
          setUndoToast(null);
        }, 7000);
        setUndoTimer(timer);
      } else {
        const res = await api.bulkDeleteProducts(deleteTarget.ids);
        setDeleteTarget(null);
        setSelectedIds([]);
        if (detailProduct && deleteTarget.ids.includes(detailProduct.id)) {
          setDetailProduct(null);
        }
        alert(`Successfully deleted ${res.deleted_count} product(s).`);
      }
      await loadProducts();
    } catch (err: any) {
      setDeleteError(err.message || 'Deletion failed. Product may be in an active cart.');
    } finally {
      setIsDeleting(false);
    }
  };

  const handleUndo = async () => {
    if (!undoToast?.id) return;
    const targetId = undoToast.id;
    const targetName = undoToast.name;
    if (undoTimer) clearTimeout(undoTimer);
    setUndoToast(null);

    try {
      await api.restoreProduct(targetId);
      alert(`Product '${targetName}' has been restored.`);
      await loadProducts();
    } catch (err: any) {
      alert(`Failed to restore product: ${err.message || 'Unknown error'}`);
    }
  };

  const handleToggleSelect = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (selectedIds.includes(id)) {
      setSelectedIds(selectedIds.filter((item) => item !== id));
    } else {
      setSelectedIds([...selectedIds, id]);
    }
  };

  const handleToggleSelectAll = () => {
    if (selectedIds.length === products.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(products.map((p) => p.id));
    }
  };

  const handleOpenDetail = (prod: Product) => {
    setDetailProduct(prod);
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Top Header & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-200 dark:border-slate-800">
        <div>
          <h1 className="text-2xl font-bold font-display text-slate-900 dark:text-white">
            Product Catalog & Inventory
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Manage barcodes, prices, stock quantities, and 360-degree vision enrollment models.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* CSV Bulk Import */}
          <label className="bg-white dark:bg-slate-800 hover:bg-slate-50 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 text-xs font-semibold px-3 py-2.5 rounded-xl cursor-pointer flex items-center gap-1.5 shadow-sm active:scale-95 transition-all">
            <Upload className="w-3.5 h-3.5 text-blue-500" />
            <span>Bulk CSV Import</span>
            <input type="file" accept=".csv" onChange={handleCSVUpload} className="hidden" />
          </label>

          {/* Add New Product Button */}
          <button
            onClick={() => setIsAddOpen(true)}
            className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold px-4 py-2.5 rounded-xl flex items-center gap-1.5 shadow-md shadow-emerald-600/30 active:scale-95 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>Add New Item</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1 relative">
          <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by product name, brand, or barcode..."
            className="w-full bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl pl-10 pr-4 py-2.5 text-xs text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-emerald-500 shadow-sm"
          />
        </div>

        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-2xl px-4 py-2.5 text-xs text-slate-700 dark:text-slate-200 focus:outline-none shadow-sm"
        >
          <option value="All">All Categories</option>
          <option value="Dairy">Dairy</option>
          <option value="Confectionery">Confectionery</option>
          <option value="Beverages">Beverages</option>
          <option value="Breakfast & Cereals">Breakfast & Cereals</option>
          <option value="Snacks">Snacks</option>
          <option value="Groceries & Staples">Groceries & Staples</option>
        </select>
      </div>

      {/* Bulk Selection Action Bar */}
      {selectedIds.length > 0 && (
        <div className="bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-800 rounded-2xl p-3 px-4 flex items-center justify-between text-xs animate-fade-in shadow-sm">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="font-semibold text-emerald-900 dark:text-emerald-200">
              {selectedIds.length} {selectedIds.length === 1 ? 'product' : 'products'} selected
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelectedIds([])}
              className="px-3 py-1.5 rounded-xl border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 font-semibold transition-colors"
            >
              Deselect All
            </button>
            <button
              onClick={handleOpenDeleteBulk}
              className="px-3.5 py-1.5 rounded-xl bg-red-600 hover:bg-red-700 text-white font-semibold flex items-center gap-1.5 shadow-md shadow-red-600/20 active:scale-95 transition-all"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Delete Selected ({selectedIds.length})</span>
            </button>
          </div>
        </div>
      )}

      {/* Products Data Table */}
      <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50 text-slate-400 uppercase font-semibold">
                <th className="p-4 w-10 text-center">
                  <input
                    type="checkbox"
                    checked={products.length > 0 && selectedIds.length === products.length}
                    onChange={handleToggleSelectAll}
                    className="rounded border-slate-300 dark:border-slate-700 text-emerald-600 focus:ring-emerald-500 cursor-pointer"
                    title="Select / Deselect All"
                  />
                </th>
                <th className="p-4">Product Details</th>
                <th className="p-4">Barcode</th>
                <th className="p-4">Price</th>
                <th className="p-4">Stock</th>
                <th className="p-4">360° Vision AI</th>
                <th className="p-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-slate-700 dark:text-slate-300">
              {products.map((p) => {
                const isSelected = selectedIds.includes(p.id);
                return (
                  <tr
                    key={p.id}
                    onClick={() => handleOpenDetail(p)}
                    className={`hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors cursor-pointer ${
                      isSelected ? 'bg-emerald-50/30 dark:bg-emerald-950/20' : ''
                    }`}
                  >
                    <td className="p-4 w-10 text-center" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={(e) => handleToggleSelect(p.id, e as any)}
                        className="rounded border-slate-300 dark:border-slate-700 text-emerald-600 focus:ring-emerald-500 cursor-pointer"
                      />
                    </td>
                    <td className="p-4">
                      <div className="flex items-center gap-3">
                        <img
                          src={p.primary_image_url || 'https://images.unsplash.com/photo-1542838132-92c53300491e?w=100'}
                          alt={p.name}
                          className="w-10 h-10 object-cover rounded-xl border border-slate-200 dark:border-slate-700"
                        />
                        <div>
                          <div className="font-semibold text-slate-900 dark:text-white text-xs hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors">
                            {p.name}
                          </div>
                          <div className="text-[11px] text-slate-400">
                            {p.brand} • {p.category}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="p-4 font-mono font-medium">{p.barcode}</td>
                    <td className="p-4">
                      <div className="font-mono font-semibold text-slate-900 dark:text-white">
                        ₹{p.price.toFixed(2)}
                      </div>
                      {p.discount_price && (
                        <div className="text-[10px] text-emerald-500 font-mono">
                          Sale: ₹{p.discount_price.toFixed(2)}
                        </div>
                      )}
                    </td>
                    <td className="p-4 font-mono">{p.stock_quantity} units</td>
                    <td className="p-4">
                      {p.has_embeddings ? (
                        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950 px-2 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-800/50">
                          <Check className="w-3 h-3" />
                          Enrolled
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 px-2 py-0.5 rounded-full border border-amber-200 dark:border-amber-800/50">
                          Pending 360 Scan
                        </span>
                      )}
                    </td>
                    <td className="p-4 text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          onClick={() => handleOpenDetail(p)}
                          className="bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 p-1.5 rounded-xl font-semibold inline-flex items-center text-xs active:scale-95 transition-all"
                          title="View Product Details"
                        >
                          <Eye className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => handleOpenEdit(p)}
                          className="bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 px-2.5 py-1.5 rounded-xl font-semibold inline-flex items-center gap-1 text-xs active:scale-95 transition-all"
                          title="Edit Product Details"
                        >
                          <Pencil className="w-3.5 h-3.5 text-blue-500" />
                          <span>Edit</span>
                        </button>
                        <button
                          onClick={(e) => handleOpenDeleteSingle(p, e)}
                          className="bg-red-50 hover:bg-red-100 dark:bg-red-950/40 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800/50 p-1.5 rounded-xl font-semibold inline-flex items-center text-xs active:scale-95 transition-all"
                          title="Delete Product"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => onStart360Scan(p)}
                          className="bg-purple-50 hover:bg-purple-100 dark:bg-purple-950/40 text-purple-600 dark:text-purple-300 border border-purple-200 dark:border-purple-800 px-2.5 py-1.5 rounded-xl font-semibold inline-flex items-center gap-1 text-xs active:scale-95 transition-all"
                          title="Enroll 360-degree Vision"
                        >
                          <Camera className="w-3.5 h-3.5" />
                          <span>Teach AI</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add New Product Modal */}
      {isAddOpen && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl w-full max-w-md p-6 shadow-2xl space-y-4">
            <h3 className="font-bold text-base font-display text-slate-900 dark:text-white">
              Add New Supermarket Item
            </h3>

            {addError && (
              <div className="p-3 bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-800 rounded-xl text-xs text-red-600 dark:text-red-400 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>{addError}</span>
              </div>
            )}

            <form onSubmit={handleCreate} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-500 mb-1">Product Name</label>
                <input
                  type="text"
                  required
                  value={newProd.name}
                  onChange={(e) => setNewProd({ ...newProd, name: e.target.value })}
                  placeholder="e.g. Amul Butter 500g"
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-500 mb-1">Brand</label>
                  <input
                    type="text"
                    required
                    value={newProd.brand}
                    onChange={(e) => setNewProd({ ...newProd, brand: e.target.value })}
                    placeholder="Amul"
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-500 mb-1">Barcode (EAN-13)</label>
                  <input
                    type="text"
                    required
                    value={newProd.barcode}
                    onChange={(e) => setNewProd({ ...newProd, barcode: e.target.value })}
                    placeholder="8901262010053"
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 font-mono text-slate-900 dark:text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-500 mb-1">Price (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={newProd.price}
                    onChange={(e) => setNewProd({ ...newProd, price: parseFloat(e.target.value) })}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-500 mb-1">Category</label>
                  <select
                    value={newProd.category}
                    onChange={(e) => setNewProd({ ...newProd, category: e.target.value })}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  >
                    <option value="Dairy">Dairy</option>
                    <option value="Confectionery">Confectionery</option>
                    <option value="Beverages">Beverages</option>
                    <option value="Breakfast & Cereals">Breakfast & Cereals</option>
                    <option value="Snacks">Snacks</option>
                    <option value="Groceries & Staples">Groceries & Staples</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="block text-slate-500 mb-1">Weight (g)</label>
                  <input
                    type="number"
                    value={newProd.weight_grams}
                    onChange={(e) => setNewProd({ ...newProd, weight_grams: parseInt(e.target.value) || 100 })}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-500 mb-1">GST Tax (%)</label>
                  <input
                    type="number"
                    step="0.5"
                    value={newProd.tax_rate}
                    onChange={(e) => setNewProd({ ...newProd, tax_rate: parseFloat(e.target.value) || 0 })}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-500 mb-1">Stock</label>
                  <input
                    type="number"
                    value={newProd.stock_quantity}
                    onChange={(e) => setNewProd({ ...newProd, stock_quantity: parseInt(e.target.value) || 0 })}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  />
                </div>
              </div>

              <div className="flex flex-col sm:flex-row gap-2 pt-3">
                <button
                  type="button"
                  disabled={isSaving}
                  onClick={() => setIsAddOpen(false)}
                  className="px-4 py-2.5 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl font-semibold hover:bg-slate-200"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSaving}
                  className="flex-1 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl font-semibold transition-colors disabled:opacity-50"
                >
                  {isSaving ? 'Saving...' : 'Save & Register'}
                </button>
                <button
                  type="button"
                  disabled={isSaving}
                  onClick={handleCreateAndScan}
                  className="flex-1 py-2.5 bg-purple-600 hover:bg-purple-700 text-white rounded-xl font-semibold shadow-md shadow-purple-600/30 flex items-center justify-center gap-1.5 transition-all disabled:opacity-50"
                >
                  <Camera className="w-3.5 h-3.5" />
                  Save & Start 360
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Product Modal */}
      {isEditOpen && editingProd && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl w-full max-w-md p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-base font-display text-slate-900 dark:text-white">
                Edit Product
              </h3>
              <span className="text-[10px] font-mono text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded-md">
                ID: {editingProd.id.slice(0, 8)}...
              </span>
            </div>

            {editError && (
              <div className="p-3 bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-800 rounded-xl text-xs text-red-600 dark:text-red-400 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>{editError}</span>
              </div>
            )}

            <form onSubmit={handleUpdate} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-500 mb-1">Product Name</label>
                <input
                  type="text"
                  required
                  value={editingProd.name}
                  onChange={(e) => setEditingProd({ ...editingProd, name: e.target.value })}
                  className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-500 mb-1">Brand</label>
                  <input
                    type="text"
                    required
                    value={editingProd.brand}
                    onChange={(e) => setEditingProd({ ...editingProd, brand: e.target.value })}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-500 mb-1">Barcode (EAN-13)</label>
                  <input
                    type="text"
                    required
                    value={editingProd.barcode}
                    onChange={(e) => setEditingProd({ ...editingProd, barcode: e.target.value })}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 font-mono text-slate-900 dark:text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-500 mb-1">Price (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={editingProd.price}
                    onChange={(e) => setEditingProd({ ...editingProd, price: parseFloat(e.target.value) || 0 })}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  />
                </div>
                <div>
                  <label className="block text-slate-500 mb-1">Sale Discount (₹)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={editingProd.discount_price || ''}
                    onChange={(e) =>
                      setEditingProd({
                        ...editingProd,
                        discount_price: e.target.value ? parseFloat(e.target.value) : undefined,
                      })
                    }
                    placeholder="Optional"
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-slate-500 mb-1">Category</label>
                  <select
                    value={editingProd.category}
                    onChange={(e) => setEditingProd({ ...editingProd, category: e.target.value })}
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  >
                    <option value="Dairy">Dairy</option>
                    <option value="Confectionery">Confectionery</option>
                    <option value="Beverages">Beverages</option>
                    <option value="Breakfast & Cereals">Breakfast & Cereals</option>
                    <option value="Snacks">Snacks</option>
                    <option value="Groceries & Staples">Groceries & Staples</option>
                    <option value="Personal Care">Personal Care</option>
                    <option value="Household & Hygiene">Household & Hygiene</option>
                  </select>
                </div>
                <div>
                  <label className="block text-slate-500 mb-1">Stock Quantity</label>
                  <input
                    type="number"
                    value={editingProd.stock_quantity}
                    onChange={(e) =>
                      setEditingProd({ ...editingProd, stock_quantity: parseInt(e.target.value) || 0 })
                    }
                    className="w-full bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl p-2.5 text-slate-900 dark:text-white"
                  />
                </div>
              </div>

              <div className="flex flex-col sm:flex-row gap-2 pt-3">
                <button
                  type="button"
                  disabled={isUpdating}
                  onClick={() => {
                    setIsEditOpen(false);
                    setEditingProd(null);
                  }}
                  className="px-4 py-2.5 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl font-semibold hover:bg-slate-200"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isUpdating}
                  className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold transition-colors disabled:opacity-50"
                >
                  {isUpdating ? 'Updating...' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Product Detail Modal */}
      {detailProduct && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl w-full max-w-lg p-6 shadow-2xl space-y-5">
            <div className="flex items-start justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <div>
                <span className="text-[10px] font-mono uppercase tracking-wider text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-950/60 px-2 py-0.5 rounded-md font-semibold">
                  Product Details
                </span>
                <h3 className="font-bold text-lg font-display text-slate-900 dark:text-white mt-1">
                  {detailProduct.name}
                </h3>
                <p className="text-xs text-slate-500">
                  {detailProduct.brand} • {detailProduct.category}
                </p>
              </div>
              <button
                onClick={() => setDetailProduct(null)}
                className="p-1.5 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 hover:text-slate-700 dark:hover:text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex flex-col sm:flex-row gap-4">
              <img
                src={detailProduct.primary_image_url || 'https://images.unsplash.com/photo-1542838132-92c53300491e?w=300'}
                alt={detailProduct.name}
                className="w-full sm:w-36 h-36 object-cover rounded-2xl border border-slate-200 dark:border-slate-700 shrink-0"
              />
              <div className="flex-1 space-y-2 text-xs">
                <div className="flex justify-between py-1 border-b border-slate-100 dark:border-slate-800/60">
                  <span className="text-slate-400">Barcode</span>
                  <span className="font-mono font-bold text-slate-900 dark:text-white">{detailProduct.barcode}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-100 dark:border-slate-800/60">
                  <span className="text-slate-400">Price (₹)</span>
                  <span className="font-mono font-bold text-slate-900 dark:text-white">
                    ₹{detailProduct.price.toFixed(2)}
                    {detailProduct.discount_price && (
                      <span className="ml-2 text-emerald-500">(Sale: ₹{detailProduct.discount_price.toFixed(2)})</span>
                    )}
                  </span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-100 dark:border-slate-800/60">
                  <span className="text-slate-400">Stock Quantity</span>
                  <span className="font-mono font-semibold text-slate-900 dark:text-white">{detailProduct.stock_quantity} units</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-100 dark:border-slate-800/60">
                  <span className="text-slate-400">Net Weight</span>
                  <span className="font-mono text-slate-900 dark:text-white">{detailProduct.weight_grams}g</span>
                </div>
                <div className="flex justify-between py-1 border-b border-slate-100 dark:border-slate-800/60">
                  <span className="text-slate-400">GST Rate</span>
                  <span className="font-mono text-slate-900 dark:text-white">{detailProduct.tax_rate}%</span>
                </div>
                <div className="flex justify-between py-1 items-center">
                  <span className="text-slate-400">360° AI Recognition</span>
                  {detailProduct.has_embeddings ? (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950 px-2 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-800/50">
                      <Check className="w-3 h-3" />
                      Enrolled in Model
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 px-2 py-0.5 rounded-full border border-amber-200 dark:border-amber-800/50">
                      Pending 360 Scan
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Action Deck on Detail Page */}
            <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-slate-100 dark:border-slate-800">
              <button
                onClick={() => {
                  const p = detailProduct;
                  setDetailProduct(null);
                  handleOpenEdit(p);
                }}
                className="flex-1 py-2.5 px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-white rounded-xl font-semibold text-xs flex items-center justify-center gap-1.5 transition-colors"
              >
                <Pencil className="w-3.5 h-3.5 text-blue-500" />
                <span>Edit Details</span>
              </button>
              <button
                onClick={() => {
                  const p = detailProduct;
                  handleOpenDeleteSingle(p);
                }}
                className="py-2.5 px-3 bg-red-50 hover:bg-red-100 dark:bg-red-950/40 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800/50 rounded-xl font-semibold text-xs flex items-center gap-1.5 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>Delete</span>
              </button>
              <button
                onClick={() => {
                  const p = detailProduct;
                  setDetailProduct(null);
                  onStart360Scan(p);
                }}
                className="flex-1 py-2.5 px-3 bg-purple-600 hover:bg-purple-700 text-white rounded-xl font-semibold text-xs flex items-center justify-center gap-1.5 shadow-md shadow-purple-600/30 transition-all"
              >
                <Camera className="w-3.5 h-3.5" />
                <span>Teach AI (360 Scan)</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-white dark:bg-[#131B2E] border border-slate-200 dark:border-slate-800 rounded-3xl w-full max-w-md p-6 shadow-2xl space-y-4">
            <div className="flex items-center gap-3 text-red-600 dark:text-red-400">
              <div className="w-10 h-10 rounded-2xl bg-red-100 dark:bg-red-950/60 flex items-center justify-center shrink-0">
                <Trash2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-bold text-base font-display text-slate-900 dark:text-white">
                  Confirm Deletion
                </h3>
                <p className="text-xs text-slate-500">
                  {deleteTarget.type === 'SINGLE' ? 'Single Product Removal' : 'Bulk Product Removal'}
                </p>
              </div>
            </div>

            <div className="p-3.5 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/50 rounded-2xl text-xs space-y-1.5">
              <p className="font-semibold text-amber-900 dark:text-amber-200">
                {deleteTarget.type === 'SINGLE'
                  ? `Delete ${deleteTarget.product.name}? This also removes its 360 scan data.`
                  : `Delete ${deleteTarget.count} selected products? This also removes their 360 scan data.`}
              </p>
              <p className="text-[11px] text-amber-700 dark:text-amber-400">
                Past receipts and transaction logs will still show this product, but the AI vision model will no longer recognize it in carts.
              </p>
            </div>

            {deleteError && (
              <div className="p-3 bg-red-50 dark:bg-red-950/60 border border-red-300 dark:border-red-800 rounded-xl text-xs text-red-700 dark:text-red-300 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <span>{deleteError}</span>
              </div>
            )}

            <div className="flex items-center gap-2 pt-2">
              <button
                type="button"
                disabled={isDeleting}
                onClick={() => {
                  setDeleteTarget(null);
                  setDeleteError(null);
                }}
                className="flex-1 py-2.5 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl font-semibold text-xs hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isDeleting}
                onClick={handleConfirmDelete}
                className="flex-1 py-2.5 bg-red-600 hover:bg-red-700 text-white rounded-xl font-semibold text-xs shadow-md shadow-red-600/30 flex items-center justify-center gap-1.5 transition-all disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>{isDeleting ? 'Deleting...' : 'Confirm Delete'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Floating Undo Notification Toast */}
      {undoToast && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-900 text-white border border-slate-700 rounded-2xl p-3.5 px-4 shadow-2xl flex items-center gap-3 animate-fade-in text-xs max-w-sm">
          <div className="flex-1">
            <span className="font-semibold">Deleted "{undoToast.name}"</span>
            <span className="block text-[10px] text-slate-400">Removed from catalog & vision index</span>
          </div>
          <button
            onClick={handleUndo}
            className="bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded-xl font-semibold flex items-center gap-1 active:scale-95 transition-all shadow-md shadow-emerald-600/30"
          >
            <Undo2 className="w-3.5 h-3.5" />
            <span>Undo</span>
          </button>
          <button
            onClick={() => setUndoToast(null)}
            className="text-slate-400 hover:text-white p-1"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
};
